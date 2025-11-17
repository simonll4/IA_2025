"""
Rate limiter for remote LLM providers (Groq default) to prevent exceeding quotas.

Reference limits (Groq llama-3.1-8b-instant free tier):
- RPM: 30 requests per minute
- RPD: 14,400 requests per day
- TPM: 6,000 tokens per minute
- TPD: 500,000 tokens per day
"""

import os
import sys
import time
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path
from threading import Lock
from typing import Any, Optional

from loguru import logger

# Ensure src package is importable
default_root = os.path.join(os.path.dirname(__file__), "..", "..", "..")
if default_root not in sys.path:
    sys.path.insert(0, default_root)

from src.pipeline.config.settings import (  # noqa: E402
    RATE_LIMIT_RPD,
    RATE_LIMIT_RPM,
    RATE_LIMIT_TPD,
    RATE_LIMIT_TPM,
)


class LLMRateLimiter:
    """Thread-safe rate limiter with token accounting per workload."""

    def __init__(
        self,
        rpm_limit: int | None = None,
        rpd_limit: int | None = None,
        tpm_limit: int | None = None,
        tpd_limit: int | None = None,
    ) -> None:
        self.rpm_limit = rpm_limit if rpm_limit is not None else RATE_LIMIT_RPM
        self.rpd_limit = rpd_limit if rpd_limit is not None else RATE_LIMIT_RPD
        self.tpm_limit = tpm_limit if tpm_limit is not None else RATE_LIMIT_TPM
        self.tpd_limit = tpd_limit if tpd_limit is not None else RATE_LIMIT_TPD

        self.minute_requests: deque[dict[str, Any]] = deque()
        self.day_requests: deque[dict[str, Any]] = deque()
        self._entries: dict[int, dict[str, Any]] = {}
        self._next_id = 0
        self._usage_breakdown: dict[str, dict[str, int]] = {}

        self.lock = Lock()

        logger.info(
            "Rate limiter initialized: RPM={rpm}/{rpm_max}, RPD={rpd}/{rpd_max}, "
            "TPM={tpm}/{tpm_max}, TPD={tpd}/{tpd_max}",
            rpm=self.rpm_limit,
            rpm_max=30,
            rpd=self.rpd_limit,
            rpd_max=1000,
            tpm=self.tpm_limit,
            tpm_max=12000,
            tpd=self.tpd_limit,
            tpd_max=100000,
        )

    def _cleanup_old_entries(self) -> None:
        now = datetime.now()
        minute_ago = now - timedelta(minutes=1)
        day_ago = now - timedelta(days=1)

        while self.minute_requests and self.minute_requests[0]["timestamp"] < minute_ago:
            self.minute_requests.popleft()

        while self.day_requests and self.day_requests[0]["timestamp"] < day_ago:
            expired = self.day_requests.popleft()
            self._entries.pop(expired["id"], None)

    def _current_usage(self) -> dict[str, int]:
        self._cleanup_old_entries()

        rpm_current = len(self.minute_requests)
        rpd_current = len(self.day_requests)
        tpm_current = sum(entry["tokens"] for entry in self.minute_requests)
        tpd_current = sum(entry["tokens"] for entry in self.day_requests)

        return {"rpm": rpm_current, "rpd": rpd_current, "tpm": tpm_current, "tpd": tpd_current}

    def check_and_wait(self, estimated_tokens: int = 1000, tag: str = "generic") -> dict[str, Any]:
        with self.lock:
            while True:
                usage = self._current_usage()

                rpm_ok = usage["rpm"] < self.rpm_limit
                rpd_ok = usage["rpd"] < self.rpd_limit
                tpm_ok = usage["tpm"] + estimated_tokens <= self.tpm_limit
                tpd_ok = usage["tpd"] + estimated_tokens <= self.tpd_limit

                if rpm_ok and rpd_ok and tpm_ok and tpd_ok:
                    now = datetime.now()
                    entry_id = self._next_id
                    self._next_id += 1
                    entry = {
                        "id": entry_id,
                        "timestamp": now,
                        "tokens": estimated_tokens,
                        "tag": tag,
                    }

                    self.minute_requests.append(entry)
                    self.day_requests.append(entry)
                    self._entries[entry_id] = entry

                    stats = self._usage_breakdown.setdefault(
                        tag,
                        {"requests": 0, "prompt_tokens": 0, "completion_tokens": 0},
                    )
                    stats["requests"] += 1

                    logger.debug(
                        "Rate limit check passed: RPM={rpm}/{rpm_max}, RPD={rpd}/{rpd_max}, "
                        "TPM={tpm}/{tpm_max}, TPD={tpd}/{tpd_max}",
                        rpm=usage["rpm"] + 1,
                        rpm_max=self.rpm_limit,
                        rpd=usage["rpd"] + 1,
                        rpd_max=self.rpd_limit,
                        tpm=usage["tpm"] + estimated_tokens,
                        tpm_max=self.tpm_limit,
                        tpd=usage["tpd"] + estimated_tokens,
                        tpd_max=self.tpd_limit,
                    )

                    return {
                        "wait_time": 0,
                        "usage": usage,
                        "limits": {
                            "rpm": self.rpm_limit,
                            "rpd": self.rpd_limit,
                            "tpm": self.tpm_limit,
                            "tpd": self.tpd_limit,
                        },
                        "entry_id": entry_id,
                        "estimated_tokens": estimated_tokens,
                    }

                wait_reasons = []
                wait_time = 1.0

                if not rpm_ok and self.minute_requests:
                    wait_reasons.append(f"RPM ({usage['rpm']}/{self.rpm_limit})")
                    oldest = self.minute_requests[0]["timestamp"]
                    wait_until = oldest + timedelta(minutes=1)
                    wait_time = max(wait_time, (wait_until - datetime.now()).total_seconds() + 0.1)

                if not rpd_ok:
                    wait_reasons.append(f"RPD ({usage['rpd']}/{self.rpd_limit})")
                    wait_time = max(wait_time, 60.0)

                if not tpm_ok and self.minute_requests:
                    wait_reasons.append(
                        f"TPM ({usage['tpm'] + estimated_tokens}/{self.tpm_limit})"
                    )
                    oldest = self.minute_requests[0]["timestamp"]
                    wait_until = oldest + timedelta(minutes=1)
                    wait_time = max(wait_time, (wait_until - datetime.now()).total_seconds() + 0.1)

                if not tpd_ok:
                    wait_reasons.append(
                        f"TPD ({usage['tpd'] + estimated_tokens}/{self.tpd_limit})"
                    )
                    wait_time = max(wait_time, 60.0)

                logger.warning(
                    "Rate limit exceeded: {reasons}. Waiting {wait:.1f}s",
                    reasons=", ".join(wait_reasons) or "unknown",
                    wait=wait_time,
                )

                time.sleep(wait_time)

    def record_actual_tokens(
        self,
        entry_id: int,
        prompt_tokens: int,
        completion_tokens: int,
    ) -> None:
        total = max(0, prompt_tokens + completion_tokens)
        with self.lock:
            entry = self._entries.get(entry_id)
            if not entry:
                logger.debug("Rate limiter entry {entry} not found", entry=entry_id)
                return

            entry["tokens"] = total
            entry["prompt_tokens"] = prompt_tokens
            entry["completion_tokens"] = completion_tokens
            tag = entry.get("tag", "generic")

            stats = self._usage_breakdown.setdefault(
                tag,
                {"requests": 0, "prompt_tokens": 0, "completion_tokens": 0},
            )
            stats["prompt_tokens"] += prompt_tokens
            stats["completion_tokens"] += completion_tokens

    def cancel_request(self, entry_id: int) -> None:
        with self.lock:
            entry = self._entries.pop(entry_id, None)
            if not entry:
                return

            tag = entry.get("tag")
            if tag in self._usage_breakdown:
                self._usage_breakdown[tag]["requests"] = max(
                    0, self._usage_breakdown[tag]["requests"] - 1
                )

            self.minute_requests = deque(
                item for item in self.minute_requests if item["id"] != entry_id
            )
            self.day_requests = deque(
                item for item in self.day_requests if item["id"] != entry_id
            )

    def retag_entry(self, entry_id: int, new_tag: str) -> None:
        """Reassign a reservation to a different workload tag."""
        with self.lock:
            entry = self._entries.get(entry_id)
            if not entry:
                return

            old_tag = entry.get("tag", "generic")
            if old_tag == new_tag:
                return

            entry["tag"] = new_tag

            if old_tag in self._usage_breakdown:
                self._usage_breakdown[old_tag]["requests"] = max(
                    0, self._usage_breakdown[old_tag]["requests"] - 1
                )

            target_stats = self._usage_breakdown.setdefault(
                new_tag,
                {"requests": 0, "prompt_tokens": 0, "completion_tokens": 0},
            )
            target_stats["requests"] += 1

    def get_stats(self) -> dict[str, Any]:
        with self.lock:
            usage = self._current_usage()
            breakdown = {
                tag: {
                    "requests": data["requests"],
                    "prompt_tokens": data["prompt_tokens"],
                    "completion_tokens": data["completion_tokens"],
                    "total_tokens": data["prompt_tokens"] + data["completion_tokens"],
                }
                for tag, data in self._usage_breakdown.items()
            }

            return {
                "usage": usage,
                "limits": {
                    "rpm": self.rpm_limit,
                    "rpd": self.rpd_limit,
                    "tpm": self.tpm_limit,
                    "tpd": self.tpd_limit,
                },
                "remaining": {
                    "rpm": max(0, self.rpm_limit - usage["rpm"]),
                    "rpd": max(0, self.rpd_limit - usage["rpd"]),
                    "tpm": max(0, self.tpm_limit - usage["tpm"]),
                    "tpd": max(0, self.tpd_limit - usage["tpd"]),
                },
                "breakdown": breakdown,
            }

# Global singleton instance
_rate_limiter: Optional[LLMRateLimiter] = None


def get_rate_limiter() -> LLMRateLimiter:
    """Get or create the global rate limiter instance."""
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = LLMRateLimiter()
    return _rate_limiter


def reset_rate_limiter():
    """Reset the global rate limiter (useful for testing)."""
    global _rate_limiter
    _rate_limiter = None
