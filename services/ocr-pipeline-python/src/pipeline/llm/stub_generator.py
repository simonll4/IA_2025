"""
Stub response generator for offline/development mode.

This module generates simulated responses when no API key is configured,
useful for development and testing without consuming API credits.
"""

import json
from decimal import Decimal
from typing import Dict, List

from .text_parsers import (
    extract_date,
    extract_invoice_number,
    find_amount,
    infer_vendor,
    to_cents,
)


def generate_stub_response(messages: List[Dict]) -> str:
    """
    Generate a stub response from the message list.
    
    Offline fallback: infers a minimal payload from the prompt text.
    Useful in development when there's no API key or connectivity.
    
    Args:
        messages: List of messages in OpenAI format (role, content)
        
    Returns:
        JSON string with stub response
    """
    user_payload = _extract_user_content(messages)
    vendor = infer_vendor(user_payload)
    invoice_number = extract_invoice_number(user_payload)
    invoice_date = extract_date(user_payload)
    
    subtotal = find_amount(
        user_payload, ["subtotal", "sub total", "net amount", "net subtotal"]
    )
    tax = find_amount(user_payload, ["tax", "vat", "sales tax"])
    total = find_amount(
        user_payload,
        [
            "amount due",
            "balance due",
            "total",
            "total due",
            "amount payable",
        ],
    )

    # Default value calculation
    if total is None:
        total = subtotal

    if subtotal is None:
        subtotal = total

    if total is None:
        total = Decimal("0")

    if subtotal is None:
        subtotal = Decimal("0")

    discount = Decimal("0")

    # Tax inference
    if tax is None and subtotal is not None and total is not None:
        tax = max(total - subtotal + discount, Decimal("0"))

    payload = {
        "schema_version": "invoice_v1",
        "invoice": {
            "invoice_number": invoice_number,
            "invoice_date": invoice_date,
            "vendor_name": vendor,
            "vendor_tax_id": None,
            "buyer_name": None,
            "currency_code": "UNK",
            "subtotal_cents": to_cents(subtotal),
            "tax_cents": to_cents(tax),
            "total_cents": to_cents(total),
            "discount_cents": to_cents(discount),
        },
        "items": [
            {
                "idx": 1,
                "description": "Total invoice amount",
                "qty": 1.0,
                "unit_price_cents": to_cents(total),
                "line_total_cents": to_cents(total),
                "category": "Other",
            }
        ],
        "notes": {
            "warnings": [
                "LLM stub enabled: configure PIPELINE_LLM_API_BASE and "
                "PIPELINE_LLM_API_KEY to enable the real extractor.",
            ],
            "confidence": 0.0,
        },
    }

    return json.dumps(payload)


def _extract_user_content(messages: List[Dict]) -> str:
    """
    Extract content from the last user message.
    
    Args:
        messages: List of messages
        
    Returns:
        Content of the last message with role="user"
    """
    for entry in reversed(messages):
        if entry.get("role") == "user":
            return entry.get("content", "")
    return ""
