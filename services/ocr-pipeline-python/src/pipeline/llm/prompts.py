"""
LLM Prompt Engineering for Invoice Extraction

This module contains carefully crafted prompts for the Groq LLM to extract
structured invoice data from OCR text. The prompts handle:

- European number formats (comma as decimal separator)
- Multi-column invoice layouts (Net worth vs Gross worth)
- Summary section mapping (Net worth → subtotal, VAT → tax, Gross worth → total)
- Category classification
- Discount detection
- Multi-item invoices with descriptor lines

Key Design Decisions:
- All prompts in English (LLM performs better)
- Explicit schema examples to ground the model
- Defensive rules to avoid hallucinations
- Clear instructions for edge cases (missing fields, ambiguous dates)
"""

from __future__ import annotations

import json
from typing import Dict

# ============================================================================
# SCHEMA DEFINITION
# ============================================================================

# Inline schema example keeps the model grounded on the target contract
# without external files. This shows the LLM exactly what structure to produce.
SCHEMA_SNIPPET = {
    "schema_version": "invoice_v1",
    "invoice": {
        "invoice_number": "string|null",
        "invoice_date": "YYYY-MM-DD",
        "vendor_name": "string",
        "vendor_tax_id": "string|null",
        "buyer_name": "string|null",
        "currency_code": "ISO4217|UNK",
        "subtotal_cents": 12345,
        "tax_cents": 2345,
        "total_cents": 14690,
        "discount_cents": 0,
    },
    "items": [
        {
            "idx": 1,
            "description": "string",
            "qty": 1.0,
            "unit_price_cents": 1234,
            "line_total_cents": 1234,
            "category": "Food|Technology|Office|Transportation|Services|Taxes|Health|Home|Other",
        }
    ],
    "notes": {
        "warnings": ["string"],
        "confidence": 0.0,
    },
}

# Mirror the classifier categories so both LLM and rule-based fallbacks stay aligned
CATEGORIES = (
    "Food, Technology, Office, Transportation, Services, Taxes, Health, Home, Other"
)


# ============================================================================
# PROMPT BUILDERS
# ============================================================================


def build_system_prompt() -> str:
    """
    Build the system message that sets LLM behavior and constraints.

    This prompt establishes:
    - Role: Expert invoice extractor
    - Output format: JSON only, no extra text
    - Schema adherence: Strict validation
    - Currency detection
    - Category classification
    - Amount calculations and validation

    Returns:
        str: System prompt for LLM
    """
    return (
        "You are an expert invoice extractor. Return ONLY valid JSON that exactly matches the "
        "'invoice_v1' schema. Do not add any text outside the JSON. Do not hallucinate values: "
        "if a field is missing, use null (or documented defaults). Convert all monetary amounts "
        "to cents (INTEGER). Detect the currency from symbols or text; when unsure, use 'UNK'. "
        "Categorize each line item using exactly one category from the provided list; if nothing fits, use 'Other'. "
        "Ensure sum(items.line_total_cents) matches invoice.subtotal_cents when available "
        "(or invoice.total_cents if subtotal is missing). Only warn when the relevant target differs "
        "by more than ~1%, and never warn solely because total_cents includes tax on top of subtotal. "
        "Capture discounts explicitly in invoice.discount_cents (0 when no discount) so that "
        "total_cents = subtotal_cents + tax_cents - discount_cents. "
        "Absolutely never emit arithmetic expressions (e.g., '322639 * 0.15'); every numeric field MUST be a literal integer."
    )


def build_user_prompt(page_text: str) -> str:
    """
    Build the user message with document text and extraction guidelines.

    This prompt provides:
    - The OCR text to extract from
    - Valid category list
    - Schema structure
    - Critical guidelines for edge cases:
      * European number format handling
      * Multi-column layout (Net worth vs Gross worth)
      * Summary section mapping
      * Descriptor line handling

    Args:
        page_text: OCR extracted text from invoice

    Returns:
        str: User prompt for LLM
    """
    schema_text = json.dumps(SCHEMA_SNIPPET, ensure_ascii=False, separators=(",", ":"))
    return (
        "Extract the structured invoice from the following document text.\n"
        "Do not output anything except the JSON payload.\n\n"
        "### Document text\n"
        f"{page_text}\n\n"
        "### Valid categories\n"
        f"{CATEGORIES}.\n\n"
        "### Schema (compact JSON)\n"
        f"{schema_text}\n\n"
        "### Guidelines\n"
        "- Return one JSON object matching 'invoice_v1'.\n"
        "- Amounts in cents (integers).\n"
        "- **CRITICAL - Number format handling (READ CAREFULLY)**:\n"
        "  * European format uses COMMA as decimal separator: '49,99' = $49.99 = 4999 cents\n"
        "  * SPACE or DOT are thousand separators (IGNORE THEM): '1 054,10' = $1,054.10 = 105410 cents\n"
        "  * Examples:\n"
        "    - '49,99' → 4999 cents (forty-nine dollars, ninety-nine cents)\n"
        "    - '177,08' → 17708 cents (one hundred seventy-seven dollars, eight cents)\n"
        "    - '958,27' → 95827 cents (nine hundred fifty-eight dollars, twenty-seven cents)\n"
        "    - '1 054,10' → 105410 cents (one thousand fifty-four dollars, ten cents)\n"
        "    - '274,95' → 27495 cents (two hundred seventy-four dollars, ninety-five cents)\n"
        "    - '779,15' → 77915 cents (seven hundred seventy-nine dollars, fifteen cents)\n"
        "  * NEVER multiply by 100 after reading the comma! The last 2 digits after comma are ALREADY cents.\n"
        "  * NEVER include thousand separators in your output - remove all spaces and dots from numbers.\n"
        "- **CRITICAL - Use correct totals**: For line items, ALWAYS use 'Gross worth' (total INCLUDING tax/VAT), NOT 'Net worth'. "
        "If you see both 'Net worth' and 'Gross worth' columns, use 'Gross worth' for line_total_cents.\n"
        "- **CRITICAL - Summary section mapping (VERY IMPORTANT)**:\n"
        "  * 'Net worth' in summary = invoice.subtotal_cents (amount BEFORE tax)\n"
        "  * 'VAT' in summary = invoice.tax_cents (tax amount)\n"
        "  * 'Gross worth' in summary = invoice.total_cents (amount AFTER tax, includes tax)\n"
        "  * Formula: Gross worth = Net worth + VAT → total_cents = subtotal_cents + tax_cents\n"
        "  * Example: If summary shows 'Net worth: $958.27, VAT: $95.83, Gross worth: $1,054.10' then:\n"
        "    subtotal_cents = 95827, tax_cents = 9583, total_cents = 105410\n"
        "- **CRITICAL - Shipping vs Tax handling**:\n"
        "  * Some invoices show 'Shipping' or 'Shipping & Handling' instead of 'Tax' or 'VAT'\n"
        "  * Shipping fees should go in tax_cents field (we use it for all additional charges)\n"
        "  * Example: 'Subtotal: $1,292.76, Discount (20%): $258.55, Shipping: $16.43, Total: $1,050.64'\n"
        "    - subtotal_cents = 129276\n"
        "    - tax_cents = 1643 (shipping fee)\n"
        "    - discount_cents = 25855\n"
        "    - total_cents = 105064\n"
        "  * Formula: total = subtotal + tax - discount\n"
        "  * Verify: 1292.76 + 16.43 - 258.55 = 1050.64 ✓\n"
        "- **CRITICAL - Item table column mapping**:\n"
        "  * If you see BOTH 'Net price' and 'Gross worth' columns in items table:\n"
        "    - items[].unit_price_cents = use 'Net price' column (unit price BEFORE tax)\n"
        "    - items[].line_total_cents = use 'Gross worth' column (line total AFTER tax)\n"
        "  * Apply the European decimal format rules to BOTH columns:\n"
        "    - 'Net price: 49,99' → unit_price_cents = 4999 (NOT 27495 from Gross worth)\n"
        "    - 'Gross worth: 274,95' → line_total_cents = 27495\n"
        "  * NEVER use 'Gross worth' for unit_price_cents - always use 'Net price' if available!\n"
        "- Missing qty → 1.0, missing unit_price → null, line_total_cents is required.\n"
        "- Detect currency from symbols/text, otherwise 'UNK'.\n"
        "- Dates in YYYY-MM-DD. Resolve ambiguous dates via month ≤ 12.\n"
        "- Use exactly one allowed category per item (fallback 'Other').\n"
        "- Only compare sum(items.line_total_cents) against invoice.subtotal_cents (or invoice.total_cents if subtotal is null). "
        "Do NOT warn when invoice.total_cents = subtotal_cents + tax_cents - discount_cents.\n"
        "- Always include invoice.discount_cents (0 if there is no discount).\n"
        "- ALL amounts in cents must be literal integers (no formulas, multiplications, or strings with symbols).\n"
        "- Some invoices list a descriptive line right below the item (category, SKU, etc.). "
        "If that line does NOT have quantity/price/amounts, concatenate it to the previous item instead of creating a new item."
    )


def build_messages(page_text: str) -> Dict[str, str]:
    """
    Build complete chat messages for LLM API.

    Returns a dict compatible with OpenAI-style chat API used by Groq
    and other providers.

    Args:
        page_text: OCR extracted text from invoice

    Returns:
        dict: {"system": str, "user": str} messages
    """
    system = build_system_prompt()
    user = build_user_prompt(page_text)
    return {"system": system, "user": user}
