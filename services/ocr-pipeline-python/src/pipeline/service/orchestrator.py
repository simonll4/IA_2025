"""
Invoice Extraction Pipeline Orchestrator

This is the main orchestrator for the invoice extraction pipeline.
It coordinates all the steps from file upload to final persistence.

Pipeline Flow:
1. File Upload → Hash-based cache check
2. Source Detection → PDF or Image
3. Text Extraction → OCR (Tesseract) or PDF parsing
4. LLM Processing → Structured JSON extraction (Groq API)
5. Normalization → Fix common LLM errors
6. Validation → Check required fields and amount consistency
7. Persistence → SQLite storage with cache for future requests
"""

from __future__ import annotations

from typing import List, Optional

from loguru import logger

from src.pipeline.category.classifier import classify_item
from src.pipeline.config.settings import (
    PDF_OCR_MAX_PAGES,
    PIPELINE_LLM_MODEL,
    TEXT_MIN_LENGTH,
)
from src.pipeline.extract.text_extractor import (
    PageText,
    extract_image_text,
    extract_pdf_text,
    join_pages,
)
from src.pipeline.ingest.loader import detect_source
from src.pipeline.llm.groq_client import call_llm
from src.pipeline.llm.prompts import build_messages
from src.pipeline.llm.validator import InvalidLLMResponse, parse_response
from src.pipeline.schema.invoice_v1 import InvoiceV1, Item, Notes
from src.pipeline.storage.db import get_document_by_hash, save_document
from src.pipeline.utils.files import compute_file_hash

# Import modular components
from .item_processor import (
    filter_false_positive_warnings,
    get_expected_line_items_total,
    merge_descriptor_items,
)
from .normalizer import (
    apply_summary_overrides,
    extract_summary_values,
    harmonize_amount_scale,
    normalize_invoice_amounts,
    recompute_discount,
)
from .validators import (
    compact_prompt_text,
    dynamic_completion_budget,
    resolve_currency,
    validate_required_fields,
)


# ============================================================================
# MAIN PIPELINE ENTRY POINT
# ============================================================================


def run_pipeline(path: str) -> dict:
    """
    Execute the complete invoice extraction pipeline.

    Args:
        path: Absolute path to PDF or image file

    Returns:
        dict: Structured invoice data

    Raises:
        ValueError: If file cannot be processed or required fields missing

    Cache Strategy:
        - Computes file hash (SHA-256) to detect duplicate uploads
        - Returns cached result if hash matches existing record
        - Saves new extractions with hash for future reuse
    """
    logger.info("Processing document: {}", path)

    # Step 1: Cache check - avoid redundant LLM calls for identical files
    file_hash = compute_file_hash(path)
    cached = get_document_by_hash(file_hash)
    if cached:
        logger.info("Cache hit by file hash")
        return cached

    # Step 2: Determine file type (PDF vs Image)
    source = detect_source(path)
    logger.debug("Detected source type: {}", source)

    # Step 3: Extract text via OCR or PDF parser
    pages = _extract_pages(path, source)
    _ensure_pages(pages)

    # Step 4: Prepare text for LLM processing
    joined = join_pages(pages)
    compact_joined = compact_prompt_text(joined)
    raw_text = "\n".join(line for page in pages for line in page.lines)

    # Build chat messages for LLM
    messages = build_messages(compact_joined)
    llm_messages = [
        {"role": "system", "content": messages["system"]},
        {"role": "user", "content": messages["user"]},
    ]

    # Step 5: Call LLM to extract structured data
    logger.debug("Invoking Groq LLM model={model}", model=PIPELINE_LLM_MODEL)
    completion_budget = dynamic_completion_budget(len(pages))
    response_text = call_llm(
        llm_messages,
        temperature=0.0,
        max_tokens=completion_budget,
        usage_tag="pipeline",
    )

    # Step 6: Parse,normalize , and validate
    model = _parse_and_normalize(response_text, joined)
    payload = model.model_dump(mode="json")

    # Step 7: Persist to database with cache
    save_document(path, file_hash, raw_text, payload)
    return payload


# ============================================================================
# TEXT EXTRACTION
# ============================================================================


def _extract_pages(path: str, source: str) -> List[PageText]:
    """Extract text from PDF or image file."""
    if source == "pdf":
        return extract_pdf_text(path, max_pages=PDF_OCR_MAX_PAGES)
    return extract_image_text(path)


def _ensure_pages(pages: List[PageText]) -> None:
    """
    Validate that OCR extraction produced usable text content.

    Raises:
        ValueError: If no text extracted or text too short
    """
    if not pages:
        raise ValueError("No text could be extracted from the document")

    total_chars = sum(len(line) for page in pages for line in page.lines)
    if total_chars == 0:
        raise ValueError("No text could be extracted from the document")

    if total_chars < TEXT_MIN_LENGTH:
        logger.warning(
            "Extracted text is very short ({chars} characters, recommended minimum {min})",
            chars=total_chars,
            min=TEXT_MIN_LENGTH,
        )


# ============================================================================
# PARSING & NORMALIZATION
# ============================================================================


def _parse_and_normalize(raw: str, document_text: str) -> InvoiceV1:
    """
    Parse LLM response and apply all normalization rules.

    Steps:
    1. Parse JSON response from LLM
    2. Resolve currency code
    3. Extract summary values from OCR text
    4. Apply defensive discount detection
    5. Normalize amounts (fix LLM errors)
    6. Classify items and fill defaults
    7. Harmonize amount scales
    8. Validate totals and generate warnings

    Args:
        raw: Raw JSON string from LLM
        document_text: Original OCR text for reference

    Returns:
        InvoiceV1: Normalized and validated invoice model

    Raises:
        InvalidLLMResponse: If JSON parsing fails
        ValueError: If required fields missing
    """
    # Step 1: Parse LLM response
    try:
        model = parse_response(raw)
    except InvalidLLMResponse as exc:
        logger.error("LLM returned an invalid response: {}", exc)
        raise

    # Work on a copy to preserve original for auditing
    data = model.model_copy(deep=True)
    invoice = data.invoice

    # Step 2: Currency resolution (always defaults to USD)
    invoice.currency_code = resolve_currency(invoice.currency_code, document_text)

    # Step 3: Defensive discount detection - avoid false positives
    # If no "discount" keyword found in OCR text, force discount to zero
    summary_values = extract_summary_values(document_text)
    if "discount" not in summary_values:
        doc_lower = document_text.lower() if document_text else ""
        if (
            "discount" not in doc_lower
            and "rebate" not in doc_lower
            and "descuento" not in doc_lower
        ):
            invoice.discount_cents = 0

    # Step 4: Fix LLM amount errors (Patterns 1-4)
    normalize_invoice_amounts(invoice)

    # Step 5: Apply summary overrides from OCR (AFTER pattern fixes)
    # OCR values are more reliable than LLM, so apply them last
    summary_overrides = set()  # Disable OCR overrides

    # Step 6: Process line items
    warnings: List[str] = []
    normalized_items: List[Item] = []

    # Fill missing defaults and classify each item
    for position, item in enumerate(data.items, start=1):
        qty = item.qty if item.qty is not None else 1.0
        category = (
            item.category
            or classify_item(item.description, invoice.vendor_name)
            or "Other"
        )
        normalized_items.append(
            Item(
                idx=position,
                description=item.description,
                qty=qty,
                unit_price_cents=item.unit_price_cents,
                line_total_cents=item.line_total_cents,
                category=category,
            )
        )

    # Merge descriptor lines (e.g., "Category: Electronics" below actual item)
    data.items = merge_descriptor_items(normalized_items, invoice)

    # Step 7: Check for scale issues (LLM sometimes returns 49999 instead of 4999)
    items_sum = sum(it.line_total_cents for it in data.items)
    harmonize_amount_scale(invoice, items_sum)

    # Re-normalize after scale fix
    normalize_invoice_amounts(invoice)

    # Recompute discount if not locked
    recompute_discount(invoice, discount_locked="discount" in summary_overrides)

    # Step 8: Validate line items sum matches invoice totals
    expected_sum = get_expected_line_items_total(invoice, items_sum)
    tolerance = max(1, int(expected_sum * 0.01)) if expected_sum else 1
    diff = abs(items_sum - expected_sum)
    if diff > tolerance:
        target = "subtotal" if invoice.subtotal_cents is not None else "total"
        warnings.append(f"Line item sum does not match invoice {target}")

    # Merge warnings from LLM and our validation
    notes: Optional[Notes] = data.notes
    existing_warnings: List[str] = []
    confidence: Optional[float] = None

    if notes:
        existing_warnings = filter_false_positive_warnings(
            notes.warnings or [], invoice
        )
        confidence = notes.confidence

    if warnings:
        combined = existing_warnings + warnings
        data.notes = Notes(
            warnings=combined,
            confidence=confidence,
        )
    elif notes:
        data.notes = Notes(
            warnings=existing_warnings or None,
            confidence=confidence,
        )

    # Final validation
    validate_required_fields(data)
    return data
