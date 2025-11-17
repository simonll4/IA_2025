"""
Validation Utilities

This module provides validation functions for:
- Required fields
- Date formats
- Text processing helpers
"""

from __future__ import annotations

import re
from datetime import datetime

from src.pipeline.schema.invoice_v1 import InvoiceV1


# ============================================================================
# FIELD VALIDATION
# ============================================================================


def validate_required_fields(model: InvoiceV1) -> None:
    """
    Ensure all required fields are present in the invoice.

    Raises:
        ValueError: If vendor_name, invoice_date, or items missing
    """
    if not model.invoice.vendor_name:
        raise ValueError("vendor_name missing in LLM response")

    if not model.invoice.invoice_date:
        raise ValueError("invoice_date missing in LLM response")

    validate_iso_date(model.invoice.invoice_date)

    if not model.items:
        raise ValueError("items missing in LLM response")


def validate_iso_date(value: str) -> None:
    """
    Validate date is in YYYY-MM-DD format.

    Raises:
        ValueError: If date format is invalid
    """
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError(f"Invalid date {value}") from exc


# ============================================================================
# CURRENCY RESOLUTION
# ============================================================================


def resolve_currency(currency_code: str, text: str) -> str:
    """
    Resolve currency code - always defaults to USD.

    All invoices are assumed to be in USD unless there's explicit evidence
    of another currency (€, £, etc.). Currently always returns USD.

    Args:
        currency_code: Currency from LLM extraction
        text: Original document text

    Returns:
        str: Currency code (always "USD")
    """
    return "USD"


# ============================================================================
# TEXT PROCESSING
# ============================================================================


def compact_prompt_text(text: str) -> str:
    """
    Reduce redundant newlines but preserve horizontal spacing.

    OCR often encodes column structure (Seller vs Client, etc.) via multiple
    spaces. Collapsing them causes the LLM to mix vendor/buyer fields, so we
    only trim tabs and excessive blank lines while preserving horizontal spacing.

    Args:
        text: Raw OCR text

    Returns:
        str: Compacted text with preserved spacing

    Ejemplo (antes -> después) para enviar al LLM:
        Entrada:
            "Proveedor:\tACME S.A.\n\n\nCliente:\tJuan Pérez\nDirección:\tCalle 123\n\n\nItems:\n1. Producto A"

        Salida:
            "Proveedor: ACME S.A.\n\nCliente: Juan Pérez\nDirección: Calle 123\n\nItems:\n1. Producto A"
    """
    text = text.replace("\t", " ")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def dynamic_completion_budget(page_count: int) -> int:
    """
    Scale completion tokens with document size.

    Args:
        page_count: Number of pages in document

    Returns:
        int: Max tokens for LLM completion (caps at 1024)
    """
    return min(1024, 256 + 120 * max(1, page_count))
