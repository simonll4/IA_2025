"""Simple keyword classifier to assist category assignment."""

from __future__ import annotations

from typing import Optional

from .rules import CATEGORY_KEYWORDS, CATEGORY_ORDER, VENDOR_HINTS


def _normalize(text: str) -> str:
    # Basic accent folding ensures matches succeed even if OCR introduces diacritics.
    return (
        (text or "")
        .lower()
        .replace("á", "a")
        .replace("é", "e")
        .replace("í", "i")
        .replace("ó", "o")
        .replace("ú", "u")
    )


def classify_item(description: str, vendor_name: str | None = None) -> Optional[str]:
    desc_norm = _normalize(description)
    vendor_norm = _normalize(vendor_name or "")

    # Prioritise vendor-level hints when available.
    for hint, category in VENDOR_HINTS.items():
        if hint in vendor_norm:
            return category

    best_category = None
    best_hits = 0

    for category in CATEGORY_ORDER:
        keywords = CATEGORY_KEYWORDS.get(category, [])
        hits = sum(1 for k in keywords if k in desc_norm.split())
        hits += sum(1 for k in keywords if k in desc_norm and len(k.split()) > 1)
        if hits > best_hits:
            best_category = category
            best_hits = hits

    return best_category
