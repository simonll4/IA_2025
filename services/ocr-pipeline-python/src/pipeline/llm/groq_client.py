"""
LLM client for Groq/OpenAI-compatible API calls.

This module handles communication with the chat completions endpoint,
including rate limiting, retries, and stub fallbacks for development.
"""

import json
import os
import sys
import time
from typing import Dict, List, Optional

import requests
from loguru import logger

# Ensure src package is importable when the module is executed directly
default_root = os.path.join(os.path.dirname(__file__), "..", "..")
if default_root not in sys.path:
    sys.path.insert(0, default_root)

from src.pipeline.config.settings import (
    PIPELINE_LLM_ALLOW_STUB,
    PIPELINE_LLM_API_BASE,
    PIPELINE_LLM_API_KEY,
    PIPELINE_LLM_MODEL,
)  # noqa: E402
from src.pipeline.llm.rate_limiter import get_rate_limiter  # noqa: E402
from src.pipeline.llm.stub_generator import generate_stub_response  # noqa: E402


def call_llm(
    messages: List[Dict],
    temperature: float = 0.0,
    max_tokens: int = 4096,
    usage_tag: str = "pipeline",
    allow_repair: bool = True,
) -> str:
    """
    Call the Groq chat completion endpoint used by the pipeline.

    This function orchestrates the complete LLM API call flow including:
    1. Validation of API credentials
    2. Rate limiting to avoid exceeding quotas
    3. HTTP request to the chat completions endpoint
    4. Automatic retry logic with exponential backoff
    5. Error handling for rate limits and server errors

    Args:
        messages: Conversation history in OpenAI format [{"role": "system/user", "content": "..."}]
        temperature: Controls randomness (0.0 = deterministic, 1.0 = creative)
        max_tokens: Maximum tokens in the response (not including prompt)
        usage_tag: Label for tracking usage in rate limiter metrics

    Returns:
        Raw JSON string response from the model

    Raises:
        ValueError: If API key is missing and stub mode is disabled
        RuntimeError: If all retry attempts fail or rate limits are exceeded
    """
    # STEP 1: Check if API key is configured
    # If missing, either return a stub (for development) or raise an error
    if not PIPELINE_LLM_API_KEY:
        if PIPELINE_LLM_ALLOW_STUB:
            logger.warning("PIPELINE_LLM_API_KEY missing; returning stub response")
            return generate_stub_response(messages)
        raise ValueError("PIPELINE_LLM_API_KEY not set in environment")

    # STEP 2: Initialize rate limiter to track token usage
    # This prevents exceeding Groq's API quotas (requests per minute/day, tokens per minute/day)
    rate_limiter = get_rate_limiter()

    # STEP 3: Estimate total tokens needed for this request
    # Groq charges based on both prompt tokens (input) and completion tokens (output)
    # We approximate: prompt_tokens ≈ text_length / 4 (rough heuristic)
    prompt_text = json.dumps(messages, ensure_ascii=False)
    estimated_tokens = max_tokens + max(1, len(prompt_text) // 4)

    # STEP 4: Build the HTTP request components
    # Groq exposes an OpenAI-compatible endpoint at /v1/chat/completions
    base_url = (PIPELINE_LLM_API_BASE or "https://api.groq.com/openai/v1").rstrip("/")
    url = f"{base_url}/chat/completions"

    # STEP 5: Set up authentication and content headers
    # Authorization uses Bearer token (API key)
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {PIPELINE_LLM_API_KEY}",
    }

    # STEP 6: Construct request body following OpenAI spec
    body = {
        # Model to use (e.g., "llama-3.3-70b-versatile")
        "model": PIPELINE_LLM_MODEL,
        # Conversation history in OpenAI format
        # Each message has "role" (system/user/assistant) and "content" (text)
        "messages": messages,
        # Temperature: 0.0 = deterministic, 1.0 = creative/random
        # We use 0.0 for structured extraction to ensure consistency
        "temperature": temperature,
        # Maximum tokens the model can generate (not including prompt)
        # Groq bills separately for prompt_tokens and completion_tokens
        "max_tokens": max_tokens,
        # Force JSON output mode (critical for structured data extraction)
        # Model MUST return valid JSON or request fails
        "response_format": {"type": "json_object"},
    }

    # STEP 7: Retry loop with exponential backoff
    # We attempt up to 4 times to handle transient failures (network issues, rate limits, server errors)
    response: Optional[requests.Response] = None
    for attempt in range(4):
        entry_id = None  # Track this request in the rate limiter
        try:
            if rate_limiter:
                rate_info = rate_limiter.check_and_wait(estimated_tokens, tag=usage_tag)
                entry_id = rate_info.get("entry_id")
                if rate_info.get("wait_time", 0) > 0:
                    logger.info(
                        "Rate limiter waited {wait:.1f}s before request",
                        wait=rate_info["wait_time"],
                    )

            logger.debug(
                "Calling Groq chat API (attempt {attempt})",
                attempt=attempt + 1,
            )
            response = requests.post(url, headers=headers, json=body, timeout=60)

            # STEP 8: Handle successful response (HTTP 200)
            if response.status_code == 200:
                data = response.json()

                # Extract the generated text from the first choice
                # OpenAI format: {choices: [{message: {role, content}}]}
                content = data["choices"][0]["message"]["content"]
                logger.debug(
                    "Groq response received: {chars} chars",
                    chars=len(content),
                )

                # STEP 8a: Extract actual token usage from response
                # Groq returns real token counts (more accurate than our estimate)
                usage = data.get("usage") or {}
                prompt_tokens = usage.get("prompt_tokens")
                completion_tokens = usage.get("completion_tokens", 0)

                # If prompt_tokens not provided, fall back to our estimate
                if prompt_tokens is None:
                    prompt_tokens = max(0, estimated_tokens - max_tokens)

                # STEP 8b: Update rate limiter with actual usage
                # This ensures accurate tracking for quota management
                if rate_limiter and entry_id is not None:
                    rate_limiter.record_actual_tokens(
                        entry_id,
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                    )

                # Success! Return the JSON content
                return content

            # STEP 9: Handle rate limit errors (HTTP 429)
            # This means we've exceeded Groq's quotas (requests per minute, tokens per day, etc.)
            if response.status_code == 429:
                # STEP 9a: Extract rate limit info from response headers
                # Groq provides valuable debugging info in headers:
                # - retry-after: How long to wait (in seconds)
                # - x-ratelimit-remaining-requests: Requests left in current window
                # - x-ratelimit-remaining-tokens: Tokens left in current window
                retry_after = response.headers.get("retry-after", "60")
                remaining_requests = response.headers.get(
                    "x-ratelimit-remaining-requests", "unknown"
                )
                remaining_tokens = response.headers.get(
                    "x-ratelimit-remaining-tokens", "unknown"
                )

                logger.warning(
                    "Groq rate limit (429): remaining_requests={req}, remaining_tokens={tok}, retry_after={retry}s",
                    req=remaining_requests,
                    tok=remaining_tokens,
                    retry=retry_after,
                )

                # STEP 9b: Cancel this request in the rate limiter
                # Since it failed, we shouldn't count it against our quota
                if rate_limiter and entry_id is not None:
                    rate_limiter.cancel_request(entry_id)

                # STEP 9c: Give up after 3 retries (4th attempt)
                if attempt >= 3:
                    break

                # STEP 9d: Wait before retrying
                # Prefer the server's retry-after value, but cap at 60s
                # Fall back to exponential backoff (2^attempt) if retry-after is invalid
                wait_time = (
                    min(int(retry_after), 60) if retry_after.isdigit() else 2**attempt
                )
                logger.info("Waiting {wait}s before retry…", wait=wait_time)
                time.sleep(wait_time)
                continue  # Retry the request            # STEP 10: Handle server errors (HTTP 5xx)
            # These are transient issues on Groq's side - retry is appropriate
            if response.status_code in (500, 502, 503):
                # Exponential backoff: 1s, 2s, 4s, 8s
                wait_time = 2**attempt
                logger.warning(
                    "Groq API error {code}, retrying in {wait}s (attempt {idx}/4)",
                    code=response.status_code,
                    wait=wait_time,
                    idx=attempt + 1,
                )

                # Cancel in rate limiter since request failed
                if rate_limiter and entry_id is not None:
                    rate_limiter.cancel_request(entry_id)

                time.sleep(wait_time)
                continue  # Retry the request

            # STEP 11: Handle validation-aware HTTP errors (4xx client errors, etc.)
            if response.status_code == 400:
                # Always cancel the token reservation because the request failed
                if rate_limiter and entry_id is not None:
                    rate_limiter.cancel_request(entry_id)

                fallback = (
                    _attempt_failed_generation_repair(
                        response=response,
                        max_tokens=max_tokens,
                        usage_tag=usage_tag,
                        allow_repair=allow_repair,
                    )
                    if allow_repair
                    else None
                )
                if fallback:
                    return fallback

                logger.error(
                    "Groq API error: {code} - {body}",
                    code=response.status_code,
                    body=response.text,
                )
                response.raise_for_status()

            # STEP 11b: Handle all other HTTP errors (auth, malformed requests)
            logger.error(
                "Groq API error: {code} - {body}",
                code=response.status_code,
                body=response.text,
            )
            response.raise_for_status()  # Raise HTTPError

        # STEP 12: Handle network timeouts
        # Request took longer than 60s - possibly server overload or network issues
        except requests.exceptions.Timeout:
            logger.warning(
                "Groq API timeout (attempt {idx}/4)",
                idx=attempt + 1,
            )

            # Retry up to 3 times (attempts 0, 1, 2)
            if attempt < 3:
                if rate_limiter and entry_id is not None:
                    rate_limiter.cancel_request(entry_id)
                time.sleep(2**attempt)  # Exponential backoff
                continue
            raise  # Give up on final attempt

        # STEP 13: Handle any other unexpected exceptions
        # (Network errors, JSON decode errors, etc.)
        except Exception as exc:
            logger.error(
                "Groq API exception: {error}",
                error=exc,
            )

            # Retry up to 3 times
            if attempt < 3:
                if rate_limiter and entry_id is not None:
                    rate_limiter.cancel_request(entry_id)
                time.sleep(2**attempt)  # Exponential backoff
                continue
            raise  # Re-raise on final attempt

        # STEP 14: Clean up if request failed but didn't raise an exception
        # This shouldn't happen in normal flow, but ensures rate limiter cleanup
        if rate_limiter and entry_id is not None:
            rate_limiter.cancel_request(entry_id)

    # STEP 15: Handle final 429 after all retries exhausted
    # If we broke out of the loop with a 429, check if it's a daily limit
    if response and response.status_code == 429:
        retry_after = response.headers.get("retry-after", "unknown")
        remaining_tokens = response.headers.get("x-ratelimit-remaining-tokens", "0")
        reset_tokens = response.headers.get("x-ratelimit-reset-tokens", "unknown")

        # Check if daily token quota is exhausted (most common limit)
        if remaining_tokens == "0":
            raise RuntimeError(
                f"Groq daily token limit reached. Tokens reset in: {reset_tokens}."
            )

        # Otherwise it's a per-minute limit
        raise RuntimeError(f"Groq rate limit reached. Retry after: {retry_after}s.")

    # STEP 16: If we got here, all retries failed for unknown reasons
    raise RuntimeError("Groq API call failed after all retries")


# Backward compatibility aliases for legacy code
call_groq = call_llm  # Old name (typo-safe)
call_grok = call_llm  # Alternative spelling


def _attempt_failed_generation_repair(
    response: requests.Response,
    max_tokens: int,
    usage_tag: str,
    allow_repair: bool,
) -> Optional[str]:
    """Salvage Groq json_validate_failed errors by repairing the returned payload."""

    try:
        error = response.json().get("error", {})
    except ValueError:
        return None

    if error.get("code") != "json_validate_failed":
        return None

    failed_generation = error.get("failed_generation")
    if not failed_generation:
        return None

    sanitized = _strip_code_fence(failed_generation.strip())
    if not sanitized:
        return None

    # If Groq already produced valid JSON but failed schema validation, accept it directly
    try:
        json.loads(sanitized)
        logger.warning(
            "Groq JSON validation failed upstream; reusing failed_generation payload"
        )
        return sanitized
    except json.JSONDecodeError:
        pass

    if not allow_repair:
        return None

    logger.warning("Groq JSON invalid syntax; requesting repair fallback")
    repair_messages = [
        {
            "role": "system",
            "content": (
                "You fix JSON payloads for invoices. Return ONLY valid JSON that matches the "
                "'invoice_v1' schema. Never include explanations, markdown, or code fences."
            ),
        },
        {
            "role": "user",
            "content": (
                "The following JSON must be corrected to valid syntax without inventing new fields. "
                "Preserve the same values and structure.\n"
                f"Invalid JSON:\n{sanitized}"
            ),
        },
    ]

    try:
        return call_llm(
            repair_messages,
            temperature=0.0,
            max_tokens=max_tokens,
            usage_tag=f"{usage_tag}_repair",
            allow_repair=False,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Groq JSON repair attempt failed: {error}", error=exc)
        return None


def _strip_code_fence(payload: str) -> str:
    candidate = payload.strip()
    if candidate.startswith("```"):
        candidate = candidate.strip("`").strip()
        if candidate.startswith("json"):
            candidate = candidate[4:].strip()
    return candidate
