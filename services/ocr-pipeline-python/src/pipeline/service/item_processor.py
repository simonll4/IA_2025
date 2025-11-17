"""
Item Processing and Validation

This module handles all line item operations:
- Merging descriptor lines with actual items
- Filtering summary-only items
- Validating line item totals
- Filtering false positive warnings
"""

from __future__ import annotations

import re
from typing import List

from src.pipeline.schema.invoice_v1 import Invoice, Item


# ============================================================================
# ITEM MERGING & FILTERING
# ============================================================================


def merge_descriptor_items(items: List[Item], invoice: Invoice) -> List[Item]:
    """
    Merge descriptor lines with their parent items.
    
    Some invoices list descriptive lines below items (SKU, category, etc.)
    that don't have quantities or prices. This merges them into the description
    of the previous item.
    
    Args:
        items: List of items to process
        invoice: Parent invoice (for summary values)
        
    Returns:
        Filtered and merged list of items
    """
    if not items:
        return items

    merged: List[Item] = []
    
    for item in items:
        if not merged:
            merged.append(item)
            continue

        # Skip summary-only items (discount, shipping, tax lines)
        if is_summary_only_item(item, invoice):
            continue

        # Merge descriptor lines into previous item
        if is_descriptor_line(item, merged[-1], invoice):
            merged[-1].description = (
                f"{merged[-1].description} {item.description}".strip()
            )
            continue

        merged.append(item)

    # Reindex items
    for idx, item in enumerate(merged, start=1):
        item.idx = idx
    
    return merged


def is_summary_only_item(item: Item, invoice: Invoice) -> bool:
    """
    Check if item is actually a summary line (discount, shipping, tax).
    
    These should be filtered out as they're captured in invoice-level fields.
    
    Args:
        item: Item to check
        invoice: Parent invoice
        
    Returns:
        True if item is a summary line
    """
    if not item.description:
        return False
    
    description = item.description.lower()
    
    # Check for summary keywords
    keywords = (
        "discount", "shipping", "freight", "delivery", "handling",
        "fees", "tax", "vat", "gst", "iva", "duty", "balance", "subtotal",
    )
    if any(word in description for word in keywords):
        return True
    
    # Check if amount matches a summary field
    if item.line_total_cents in {invoice.discount_cents, invoice.tax_cents}:
        return True
    
    return False


def is_descriptor_line(item: Item, previous: Item, invoice: Invoice) -> bool:
    """
    Check if item is a descriptor line (should merge with previous).
    
    Descriptor lines have:
    - No unit price (or 0)
    - No quantity (or 1)
    - No currency amounts in description
    - Line total matches previous item or is 0
    
    Args:
        item: Item to check
        previous: Previous item in list
        invoice: Parent invoice
        
    Returns:
        True if item should be merged with previous
    """
    if not item.description:
        return False
    
    # Must have no price
    if item.unit_price_cents not in (None, 0):
        return False
    
    # Must have no/default quantity
    if item.qty not in (None, 0, 1, 1.0):
        return False
    
    # Must not contain currency amounts
    if contains_currency_amount(item.description):
        return False

    # Line total should match previous or be negligible
    candidate_totals = {
        previous.line_total_cents,
        invoice.discount_cents,
        invoice.tax_cents,
        None,
        0,
    }
    if item.line_total_cents not in candidate_totals:
        return False
    
    return True


# Currency pattern for detecting amounts in text
CURRENCY_TOKEN = re.compile(r"[$€£]|(\d+[.,]\d{1,2})")


def contains_currency_amount(text: str) -> bool:
    """
    Check if text contains currency symbols or amounts.
    
    Args:
        text: Text to check
        
    Returns:
        True if currency-like patterns found
    """
    return bool(CURRENCY_TOKEN.search(text))


# ============================================================================
# ITEM VALIDATION
# ============================================================================


def get_expected_line_items_total(invoice: Invoice, items_sum: int) -> int:
    """
    Determine which invoice field to compare line items sum against.
    
    Compares items_sum to available invoice totals and returns the closest.
    
    Args:
        invoice: Invoice with totals
        items_sum: Sum of all line item amounts
        
    Returns:
        Best matching total to compare against
    """
    candidates = []
    
    if invoice.subtotal_cents is not None:
        candidates.append(invoice.subtotal_cents)
    
    if invoice.total_cents is not None:
        candidates.append(invoice.total_cents)
    
    if not candidates:
        return items_sum
    
    # Return the candidate closest to items_sum
    return min(candidates, key=lambda value: abs(items_sum - value))


def totals_are_consistent(invoice: Invoice) -> bool:
    """
    Check if invoice totals are mathematically consistent.
    
    Validates: total = subtotal + tax - discount (within tolerance)
    
    Args:
        invoice: Invoice to check
        
    Returns:
        True if totals are consistent
    """
    if (
        invoice.subtotal_cents is None
        or invoice.tax_cents is None
        or invoice.total_cents is None
    ):
        return True  # Can't validate if missing
    
    tolerance = max(1, int(invoice.total_cents * 0.001))
    discount = invoice.discount_cents or 0
    expected_total = invoice.subtotal_cents + invoice.tax_cents - discount
    
    return abs(expected_total - invoice.total_cents) <= tolerance


def filter_false_positive_warnings(warnings: List[str], invoice: Invoice) -> List[str]:
    """
    Remove warnings that are false positives due to consistent totals.
    
    If invoice totals are mathematically consistent, remove warnings about
    mismatches (they're likely just rounding differences).
    
    Args:
        warnings: List of warning messages
        invoice: Invoice to check
        
    Returns:
        Filtered list of warnings
    """
    if not warnings:
        return warnings
    
    cleaned = warnings
    
    if totals_are_consistent(invoice):
        # Remove total mismatch warnings if amounts are actually consistent
        phrases = (
            "total and subtotal disagree",
            "total line items and invoice total disagree",
            "line item sum does not match",
            "total line item amount",
        )
        
        lowered = []
        for warning in cleaned:
            if any(phrase in warning.lower() for phrase in phrases):
                continue
            lowered.append(warning)
        
        cleaned = lowered
    
    return cleaned
