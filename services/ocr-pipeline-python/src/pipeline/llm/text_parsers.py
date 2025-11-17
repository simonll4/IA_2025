"""
Text parsing utilities for invoice data extraction.

This module contains helper functions to extract structured information
from OCR text, including dates, amounts, invoice numbers, etc.
"""

import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import List, Optional


def extract_invoice_number(text: str) -> Optional[str]:
    """
    Search for common invoice number patterns in text.
    
    Args:
        text: Text to search for invoice number
        
    Returns:
        Extracted invoice number or None if not found
    """
    patterns = [
        r"invoice\s*no\.?\s*([\w-]+)",
        r"invoice\s*#\s*([\w-]+)",
    ]
    lower = text.lower()
    for pattern in patterns:
        match = re.search(pattern, lower, re.IGNORECASE)
        if match:
            return match.group(1).upper()
    return None


def extract_date(text: str) -> str:
    """
    Extract dates from text in various formats and normalize to ISO.
    
    Supports:
    - ISO format: YYYY-MM-DD
    - EU format: DD/MM/YYYY or DD-MM-YYYY
    - US format: YYYY/MM/DD
    
    Args:
        text: Text to search for date
        
    Returns:
        Date in ISO format (YYYY-MM-DD) or today's date if not found
    """
    # Prefer ISO format
    iso = re.search(r"(\d{4}-\d{2}-\d{2})", text)
    if iso:
        return iso.group(1)

    # European format: DD/MM/YYYY
    euro = re.search(r"(\d{2})[/-](\d{2})[/-](\d{4})", text)
    if euro:
        day, month, year = euro.groups()
        return f"{year}-{month}-{day}"

    # US format: YYYY/MM/DD
    us = re.search(r"(\d{4})/(\d{2})/(\d{2})", text)
    if us:
        year, month, day = us.groups()
        return f"{year}-{month}-{day}"

    return date.today().isoformat()


def find_amount(text: str, keywords: List[str]) -> Optional[Decimal]:
    """
    Search for lines with certain keywords and extract an amount.
    
    Args:
        text: Text to search in
        keywords: List of keywords to look for (e.g., ["total", "subtotal"])
        
    Returns:
        Amount as Decimal or None if not found
    """
    for line in iter_lines(text):
        lower = line.lower()
        if any(keyword in lower for keyword in keywords):
            amount = extract_number(line)
            if amount is not None:
                return amount
    return None


def extract_number(text: str) -> Optional[Decimal]:
    """
    Normalize locale separators (dots/commas/spaces) and convert to Decimal.
    
    Handles different numeric formats:
    - 1,234.56 (US)
    - 1.234,56 (EU)
    - 1 234,56 (spaces)
    
    Args:
        text: Text containing the number
        
    Returns:
        Number as Decimal or None if extraction fails
    """
    match = re.search(r"[-+]?\d[\d., ]*", text)
    if not match:
        return None

    raw = match.group(0)
    normalized = re.sub(r"[^0-9.,]", "", raw)

    # Normalize separators
    if normalized.count(".") > 1 and normalized.count(",") == 0:
        normalized = normalized.replace(".", "")
    if normalized.count(",") > 1 and normalized.count(".") == 0:
        normalized = normalized.replace(",", "")
    if "." in normalized and "," in normalized:
        if normalized.rfind(",") > normalized.rfind("."):
            # EU format: 1.234,56
            normalized = normalized.replace(".", "").replace(",", ".")
        else:
            # US format: 1,234.56
            normalized = normalized.replace(",", "")
    elif "," in normalized and "." not in normalized:
        # Only commas, probably decimals
        normalized = normalized.replace(",", ".")

    try:
        return Decimal(normalized)
    except (InvalidOperation, ValueError):
        return None


def to_cents(value: Optional[Decimal]) -> int:
    """
    Convert a Decimal to cents (integer).
    
    Args:
        value: Decimal value or None
        
    Returns:
        Value in cents as integer (0 if value is None)
    """
    if value is None:
        return 0
    return int((value * 100).quantize(Decimal("1")))


def iter_lines(text: str) -> List[str]:
    """
    Return non-empty lines from text, trimmed.
    
    Args:
        text: Text to split into lines
        
    Returns:
        List of non-empty lines
    """
    return [line.strip() for line in text.splitlines() if line.strip()]


def infer_vendor(text: str) -> str:
    """
    Heuristic to infer vendor name from text.
    
    Looks for the first non-trivial line that doesn't look like a label.
    
    Args:
        text: Invoice text
        
    Returns:
        Inferred vendor name
    """
    for line in iter_lines(text):
        if len(line) > 2 and not any(
            keyword in line.lower() for keyword in ("invoice", ":")
        ):
            return line[:80]
    return "Demo Vendor"
