"""
Amount Normalization and LLM Error Correction

This module handles all invoice amount normalization, including:
- Fixing LLM confusion patterns (4 specific patterns)
- Currency resolution
- Scale harmonization
- Amount inference and clamping
- Summary value extraction from OCR text
- Discount recomputation

Key Patterns Fixed:
1. Gross Worth Swap: subtotal ≈ total (LLM reads wrong column)
2. Net Worth Duplication: subtotal == tax (LLM duplicates value)
3. Gross Worth in Tax: tax == total (LLM misreads summary)
4. Gross in Tax + Net Duplication: tax > total AND subtotal == total
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Dict, Optional

from loguru import logger

from src.pipeline.schema.invoice_v1 import Invoice


# ============================================================================
# MAIN NORMALIZATION FUNCTION
# ============================================================================


def normalize_invoice_amounts(invoice: Invoice) -> None:
    """
    Detect and fix common LLM amount extraction errors.

    Applies pattern-based fixes for European invoice formats where
    LLM might confuse "Net worth", "VAT", and "Gross worth" columns.

    Modifies the invoice object in-place.

    Args:
        invoice: Invoice with potentially incorrect amounts
    """
    # Extract current values
    subtotal = invoice.subtotal_cents
    tax = invoice.tax_cents
    total = invoice.total_cents
    discount = invoice.discount_cents if invoice.discount_cents is not None else 0

    # Discount should never be negative
    if discount < 0:
        discount = 0

    # ========================================================================
    # PATTERN DETECTION & CORRECTION
    # ========================================================================
    # These patterns fix LLM confusion from European invoice formats where
    # summary sections have "Net worth" (subtotal), "VAT" (tax), and
    # "Gross worth" (total). The LLM sometimes reads the wrong column values.

    # Pattern 1: Gross Worth Swap
    # Symptom: subtotal ≈ total (within 5%), tax is reasonable
    # Cause: LLM put "Gross worth" in subtotal field
    # Fix: Swap subtotal with tax
    if (
        subtotal is not None
        and tax is not None
        and total is not None
        and subtotal >= total * 0.95  # subtotal too close to total
        and tax + discount < total  # tax is smaller (makes sense)
        and tax > 0
    ):  # tax has value

        # Verify swap makes sense mathematically
        new_subtotal = tax
        new_tax = total - new_subtotal + discount

        # Ensure new tax is positive and reasonable (< subtotal)
        if new_tax > 0 and new_tax < new_subtotal:
            subtotal, tax = new_subtotal, new_tax
            logger.debug("Applied Pattern 1 fix: swapped subtotal/tax")

    # Pattern 2: Net Worth Duplication
    # Symptom: subtotal == tax exactly
    # Cause: LLM read "Net worth" for both fields
    # Fix: Recalculate tax from total - subtotal
    elif (
        subtotal is not None
        and tax is not None
        and total is not None
        and subtotal == tax  # Exact duplication
        and total > subtotal  # Total larger (makes sense)
        and total > 0
    ):

        # Calculate correct tax
        new_tax = total - subtotal + discount

        # Verify it's reasonable (positive and < subtotal)
        if new_tax > 0 and new_tax < subtotal:
            tax = new_tax
            logger.debug("Applied Pattern 2 fix: recalculated tax from total")

    # Pattern 3: Gross Worth in Tax Field
    # Symptom: tax == total exactly
    # Cause: LLM read "Gross worth" for both tax and total
    # Fix: Recalculate tax from total - subtotal
    elif (
        subtotal is not None
        and tax is not None
        and total is not None
        and tax == total  # Exact duplication
        and subtotal < total  # Subtotal smaller (makes sense)
        and subtotal > 0
    ):

        # Calculate correct tax
        new_tax = total - subtotal + discount

        # Verify it's reasonable (positive and < subtotal)
        if new_tax > 0 and new_tax < subtotal:
            tax = new_tax
            logger.debug("Applied Pattern 3 fix: recalculated tax from total")

    # Pattern 4: Gross Worth in Tax + Net Worth Duplication in Total
    # Symptom: tax > total AND subtotal == total
    # Cause: LLM put "Gross worth" in tax field AND duplicated "Net worth" in total
    # Fix: Set total = tax (gross worth), then recalculate tax
    elif (
        subtotal is not None
        and tax is not None
        and total is not None
        and tax > total  # Tax larger than total (impossible)
        and subtotal == total  # Total duplicates subtotal
        and subtotal > 0
    ):

        # The 'tax' field actually contains the gross worth (total)
        # So: total = tax, then recalculate tax
        total = tax
        tax = total - subtotal + discount
        logger.debug(
            "Applied Pattern 4 fix: tax had gross worth, total duplicated net worth"
        )

    # ========================================================================
    # VALUE CLAMPING & INFERENCE
    # ========================================================================

    def _clamp(value: Optional[int]) -> Optional[int]:
        """Ensure value is non-negative integer or None."""
        if value is None:
            return None
        return max(int(round(value)), 0)

    # Infer missing subtotal from total and tax
    if subtotal is None and total is not None:
        inferred = total - (tax or 0) + discount
        if inferred >= 0:
            subtotal = inferred

    # Infer missing tax from subtotal and total
    if tax is None and subtotal is not None and total is not None:
        inferred = total - subtotal + discount
        if inferred >= 0:
            tax = inferred

    # Infer missing total from subtotal and tax
    if total is None and subtotal is not None:
        inferred = subtotal + (tax or 0) - discount
        if inferred >= 0:
            total = inferred

    # Apply clamping and save back to invoice
    invoice.subtotal_cents = _clamp(subtotal)
    invoice.tax_cents = _clamp(tax)
    invoice.total_cents = _clamp(total)
    invoice.discount_cents = _clamp(discount) or 0


# ============================================================================
# SCALE HARMONIZATION
# ============================================================================


def harmonize_amount_scale(invoice: Invoice, items_sum: int) -> None:
    """
    Detect and fix amount scale issues (e.g., 49999 vs 4999).

    Sometimes LLM returns amounts in wrong scale. This detects common
    scale factors (1000x, 100x, 10x) and corrects invoice amounts.

    Args:
        invoice: Invoice to fix (modified in-place)
        items_sum: Sum of all line item amounts
    """
    if not items_sum or items_sum <= 0:
        return

    scale = _detect_scale_factor(invoice, items_sum)
    if not scale or scale == 1:
        return

    # Apply scale correction to all amounts
    for field in ("subtotal_cents", "tax_cents", "total_cents", "discount_cents"):
        value = getattr(invoice, field)
        if value is not None:
            setattr(invoice, field, max(int(round(value / scale)), 0))


def _detect_scale_factor(invoice: Invoice, items_sum: int) -> Optional[int]:
    """
    Detect if invoice amounts are off by a scale factor.

    Returns:
        Scale factor (1000, 100, 10, or 1)
    """
    candidates = (1000, 100, 10)

    for amount in (
        invoice.total_cents,
        invoice.subtotal_cents,
        invoice.tax_cents,
        invoice.discount_cents,
    ):
        if amount is None or amount <= 0:
            continue

        ratio = amount / items_sum
        for candidate in candidates:
            tolerance = max(0.05 * candidate, 0.5)
            if abs(ratio - candidate) <= tolerance:
                return candidate

    return 1


# ============================================================================
# DISCOUNT RECOMPUTATION
# ============================================================================


def recompute_discount(invoice: Invoice, discount_locked: bool = False) -> None:
    """
    Recompute discount from totals if not explicitly locked.

    Args:
        invoice: Invoice to update (modified in-place)
        discount_locked: If True, don't modify discount
    """
    if discount_locked:
        return

    subtotal = invoice.subtotal_cents
    total = invoice.total_cents

    if subtotal is None or total is None:
        return

    additions = invoice.tax_cents or 0
    expected = subtotal + additions - total
    tolerance = max(1, int(max(total, 1) * 0.001))

    # If expected is slightly negative due to rounding, set to 0
    if expected < 0 and abs(expected) <= tolerance:
        expected = 0

    if expected < 0:
        return

    # Update discount if it differs significantly
    if abs(expected - (invoice.discount_cents or 0)) > tolerance:
        invoice.discount_cents = expected


# ============================================================================
# SUMMARY VALUE EXTRACTION
# ============================================================================


# Regex patterns for extracting summary values from OCR text
SUMMARY_LABEL_PATTERN = re.compile(
    r"(Subtotal|Sub-total|Total|Balance Due|Discount(?:\s*\([^)]*\))?|"
    r"Shipping|Freight|Delivery|Handling|Fees|Charge|Tax(?!\s+Id)|"
    r"Sales Tax|VAT|GST|IVA|Duty)\s*:?",
    re.IGNORECASE,
)

AMOUNT_PATTERN = re.compile(
    r"(?:[$€£]\s*)?([-+]?\d[\d,]*[.,]\d{1,2})",
    re.IGNORECASE,
)


def extract_summary_values(text: str) -> Dict[str, int]:
    """
    Extract monetary amounts from invoice summary section.

    Finds labels like "Subtotal:", "Tax:", "Total:" and their associated
    amounts in the OCR text. Handles grouped labels and filters out percentages.

    Args:
        text: OCR extracted text

    Returns:
        Dictionary mapping normalized labels to amounts in cents
        (e.g., {"subtotal": 10000, "tax": 1000, "total": 11000})
    """
    summary: Dict[str, int] = {}

    # Find all labels and amounts
    label_matches = list(SUMMARY_LABEL_PATTERN.finditer(text))
    if not label_matches:
        return summary

    amount_matches = list(AMOUNT_PATTERN.finditer(text))
    if not amount_matches:
        return summary

    # Filter out percentages (numbers followed by % or in discount context)
    valid_amounts = []
    for amount_match in amount_matches:
        after_pos = amount_match.end()
        after_text = text[after_pos : after_pos + 3].strip()
        before_text = text[max(0, amount_match.start() - 15) : amount_match.start()]

        # Skip if it's a percentage
        if after_text.startswith("%") or (
            after_text.startswith(")") and "discount" in before_text.lower()
        ):
            continue

        valid_amounts.append(amount_match)

    if not valid_amounts:
        return summary

    used_amounts = set()

    # Max distance between label and amount (80 chars = same/next line)
    MAX_AMOUNT_LABEL_DISTANCE = 80

    # Process label groups (consecutive labels without amounts between them)
    i = 0
    while i < len(label_matches):
        # Start a potential group at label i
        group_labels = [label_matches[i]]
        j = i + 1

        # Extend the group while labels are consecutive
        while j < len(label_matches):
            prev_label_end = label_matches[j - 1].end()
            curr_label_start = label_matches[j].start()

            # Check if there are amounts between labels
            amounts_between = [
                amt
                for amt in valid_amounts
                if amt not in used_amounts
                and amt.start() >= prev_label_end
                and amt.start() < curr_label_start
            ]

            if amounts_between:
                break  # Break the group

            group_labels.append(label_matches[j])
            j += 1

        # Process this group
        if len(group_labels) == 1:
            # Single label: find closest amount after it
            label_match = group_labels[0]
            label_text = label_match.group(1)
            label_end = label_match.end()

            # Find boundary (next label or end of text)
            next_label_start = (
                label_matches[i + 1].start()
                if i + 1 < len(label_matches)
                else len(text)
            )

            # Find closest amount
            closest_amount = None
            min_distance = float("inf")

            for amt in valid_amounts:
                if amt in used_amounts:
                    continue

                # Amount must appear after label and within distance
                if not (amt.start() >= label_end and amt.start() < next_label_start):
                    continue

                distance = amt.start() - label_end
                if distance > MAX_AMOUNT_LABEL_DISTANCE:
                    continue

                if distance < min_distance:
                    min_distance = distance
                    closest_amount = amt

            if closest_amount:
                amount_str = closest_amount.group(1)
                cents = parse_amount_to_cents(amount_str)
                if cents is not None:
                    normalized = normalize_summary_label(label_text)
                    if normalized == "addition":
                        summary["addition"] = summary.get("addition", 0) + cents
                    elif normalized and normalized not in summary:
                        summary[normalized] = cents
                    used_amounts.add(closest_amount)

        else:
            # Multiple labels in group: find amounts after last label
            last_label_end = group_labels[-1].end()

            # Find amounts after last label within distance
            amounts_after = [
                amt
                for amt in valid_amounts
                if amt not in used_amounts
                and amt.start() >= last_label_end
                and amt.start() - last_label_end <= MAX_AMOUNT_LABEL_DISTANCE
            ]

            # Match labels to amounts in order
            for k, label_match in enumerate(group_labels):
                if k >= len(amounts_after):
                    break

                label_text = label_match.group(1)
                amount_match = amounts_after[k]

                amount_str = amount_match.group(1)
                cents = parse_amount_to_cents(amount_str)
                if cents is None:
                    continue

                normalized = normalize_summary_label(label_text)
                if normalized == "addition":
                    summary["addition"] = summary.get("addition", 0) + cents
                elif normalized and normalized not in summary:
                    summary[normalized] = cents

                used_amounts.add(amount_match)

        # Move to next group
        i = j if j > i else i + 1

    return summary


def parse_amount_to_cents(value: str) -> Optional[int]:
    """
    Parse amount string to cents (integer).

    Handles various formats:
    - European: 1.234,56 → 123456 cents
    - US: 1,234.56 → 123456 cents
    - Simple: 49,99 → 4999 cents

    Args:
        value: Amount string (e.g., "1,234.56" or "49,99")

    Returns:
        Amount in cents or None if parsing fails
    """
    cleaned = value.strip()
    if not cleaned:
        return None

    # Remove currency symbols
    cleaned = cleaned.replace("$", "").replace("€", "").replace("£", "")
    cleaned = cleaned.replace(" ", "")

    # Handle multiple separators
    if cleaned.count(",") > 1 and "." not in cleaned:
        # European thousands: 1,234,567 → 1234567
        cleaned = cleaned.replace(",", "")
    elif cleaned.count(".") > 1 and "," not in cleaned:
        # Unusual thousands: 1.234.567 → 1234567
        cleaned = cleaned.replace(".", "")
    elif "." in cleaned and "," in cleaned:
        # Mixed: determine which is decimal
        if cleaned.rfind(",") > cleaned.rfind("."):
            # European: 1.234,56 → 1234.56
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            # US: 1,234.56 → 1234.56
            cleaned = cleaned.replace(",", "")
    else:
        # Single separator: assume comma is decimal (European default)
        cleaned = cleaned.replace(",", ".")

    try:
        cents = int(round(Decimal(cleaned) * 100))
    except InvalidOperation:
        return None

    return cents


def normalize_summary_label(label: str) -> Optional[str]:
    """
    Normalize summary label to standard field name.

    Args:
        label: Label text (e.g., "Sub-total", "VAT", "Total")

    Returns:
        Normalized label ("subtotal", "discount", "total", "addition") or None
    """
    lower = label.lower()

    if "subtotal" in lower or "sub-total" in lower:
        return "subtotal"

    if "discount" in lower or "rebate" in lower:
        return "discount"

    if "total" in lower or "balance due" in lower:
        return "total"

    # Tax, fees, shipping, etc. all go to "addition"
    if any(
        keyword in lower
        for keyword in (
            "addition",
            "shipping",
            "freight",
            "delivery",
            "handling",
            "fees",
            "charge",
            "tax",
            "vat",
            "gst",
            "iva",
            "duty",
        )
    ):
        return "addition"

    return None


def apply_summary_overrides(invoice: Invoice, summary: Dict[str, int]) -> set[str]:
    """
    Apply extracted summary values to invoice, overriding LLM values.

    Only applies overrides if the extracted values make mathematical sense:
    - Total should be >= subtotal (if both present)
    - Tax should be < subtotal (if both present)
    - All values should be positive

    Args:
        invoice: Invoice to update (modified in-place)
        summary: Extracted summary values from OCR

    Returns:
        Set of field names that were overridden
    """
    overrides: set[str] = set()

    if not summary:
        return overrides

    # Validation: Check if summary values make sense
    summary_subtotal = summary.get("subtotal")
    summary_total = summary.get("total")
    summary_tax = summary.get("addition")

    # If both subtotal and total present, validate total >= subtotal
    if summary_subtotal is not None and summary_total is not None:
        if summary_total < summary_subtotal:
            logger.warning(
                "Summary override rejected: total ({total}) < subtotal ({subtotal})",
                total=summary_total,
                subtotal=summary_subtotal,
            )
            return overrides  # Don't apply ANY overrides if values don't make sense

    # If tax and subtotal present, validate tax < subtotal
    if summary_tax is not None and summary_subtotal is not None:
        if summary_tax >= summary_subtotal:
            logger.warning(
                "Summary override rejected: tax ({tax}) >= subtotal ({subtotal})",
                tax=summary_tax,
                subtotal=summary_subtotal,
            )
            return overrides  # Don't apply ANY overrides

    # Apply overrides if validation passed
    if "subtotal" in summary:
        invoice.subtotal_cents = summary["subtotal"]
        overrides.add("subtotal")

    if "total" in summary:
        invoice.total_cents = summary["total"]
        overrides.add("total")

    if "discount" in summary:
        invoice.discount_cents = summary["discount"]
        overrides.add("discount")

    if "addition" in summary:
        invoice.tax_cents = summary["addition"]
        overrides.add("addition")

    return overrides
