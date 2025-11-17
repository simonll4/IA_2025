"""Utilities to validate LLM responses against invoice_v1 schema."""

from __future__ import annotations

import json
from typing import Any, Dict

from loguru import logger

from src.pipeline.schema.invoice_v1 import InvoiceV1, validate_invoice_payload


class InvalidLLMResponse(Exception):
    pass


def parse_response(raw: str) -> InvoiceV1:
    raw = raw.strip()
    if raw.startswith("```"):
        # Accept markdown-formatted responses by trimming the surrounding code block.
        raw = raw.strip("`").strip()
        if raw.startswith("json"):
            raw = raw[4:].strip()
    try:
        payload: Dict[str, Any] = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise InvalidLLMResponse("LLM returned invalid JSON") from exc

    try:
        # Let Pydantic handle schema validation so we get consistent error messages.
        validated = validate_invoice_payload(payload)
        logger.debug("LLM response validated successfully")
        return validated
    except Exception as exc:  # noqa: BLE001
        raise InvalidLLMResponse("LLM returned data outside the contract") from exc
