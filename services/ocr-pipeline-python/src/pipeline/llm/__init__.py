"""
LLM module for invoice extraction.

This module provides LLM client functionality, text parsing utilities,
and stub response generation for development/testing.
"""

from .groq_client import call_grok, call_groq, call_llm
from .stub_generator import generate_stub_response
from .text_parsers import (
    extract_date,
    extract_invoice_number,
    extract_number,
    find_amount,
    infer_vendor,
    iter_lines,
    to_cents,
)

__all__ = [
    # Main LLM client
    "call_llm",
    "call_groq",
    "call_grok",
    # Stub generator
    "generate_stub_response",
    # Text parsing utilities
    "extract_date",
    "extract_invoice_number",
    "extract_number",
    "find_amount",
    "infer_vendor",
    "iter_lines",
    "to_cents",
]
