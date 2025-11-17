# LLM Module

This module provides LLM client functionality for invoice extraction with support for rate limiting, retries, and offline development.

## Module Structure

### `groq_client.py`
Main LLM client for Groq/OpenAI-compatible API calls.

**Key Functions:**
- `call_llm()`: Primary function to call the chat completions endpoint
- `call_groq()`, `call_grok()`: Backward compatibility aliases

**Features:**
- Automatic retry with exponential backoff
- Rate limiting integration
- 429 (rate limit) handling with Retry-After headers
- Stub fallback for development

---

### `text_parsers.py`
Text parsing utilities for extracting structured data from OCR text.

**Functions:**
- `extract_invoice_number()`: Find invoice numbers using regex patterns
- `extract_date()`: Parse dates in various formats (ISO, EU, US) and normalize to ISO
- `find_amount()`: Search for monetary amounts by keywords
- `extract_number()`: Parse numbers with locale-aware decimal/thousand separators
- `to_cents()`: Convert Decimal amounts to integer cents
- `iter_lines()`: Get non-empty trimmed lines from text
- `infer_vendor()`: Heuristic to extract vendor name

**Supported Number Formats:**
- US: `1,234.56`
- EU: `1.234,56`
- Spaces: `1 234,56`

---

### `stub_generator.py`
Offline response generator for development without API access.

**Functions:**
- `generate_stub_response()`: Create minimal invoice payload from message text

**Use Cases:**
- Local development without API keys
- Testing without consuming API credits
- Offline mode fallback

---

### `rate_limiter.py`
Token-based rate limiting to stay within API quotas.

---

### `validator.py`
Response validation utilities.

---

### `prompts.py`
Prompt templates for LLM interactions.

---

## Usage Examples

### Basic LLM Call
```python
from src.pipeline.llm import call_llm

messages = [
    {"role": "system", "content": "You are an invoice extractor. Return only JSON."},
    {"role": "user", "content": "Invoice #12345\nTotal: $100.50"},
]

response = call_llm(messages, temperature=0.0, max_tokens=2048)
```

### Text Parsing
```python
from src.pipeline.llm import extract_date, extract_number, to_cents

# Extract date
date_str = extract_date("Invoice Date: 25/12/2023")  # Returns: "2023-12-25"

# Parse number
amount = extract_number("Total: $1,234.56")  # Returns: Decimal("1234.56")

# Convert to cents
cents = to_cents(Decimal("123.45"))  # Returns: 12345
```

### Stub Mode (Development)
```python
from src.pipeline.llm import generate_stub_response

messages = [
    {"role": "user", "content": "Invoice #INV-001\nVendor: ACME Corp\nTotal: $500.00"}
]

stub = generate_stub_response(messages)
# Returns a minimal JSON invoice payload
```

## Configuration

Set these environment variables:
- `PIPELINE_LLM_API_KEY`: Your Groq/OpenAI API key
- `PIPELINE_LLM_API_BASE`: API endpoint (default: Groq endpoint)
- `PIPELINE_LLM_MODEL`: Model to use (e.g., "llama-3.3-70b-versatile")
- `PIPELINE_LLM_ALLOW_STUB`: Enable stub fallback when no API key (default: False)

## Refactoring Benefits

1. **Separation of Concerns**: Each file has a single, clear responsibility
2. **Reusability**: Text parsing utilities can be used independently
3. **Testability**: Smaller modules are easier to unit test
4. **Maintainability**: Cleaner code structure with better organization
5. **Documentation**: Each module is self-documenting with clear docstrings

## Migration Guide

If you were importing from the old `groq_client.py`:

```python
# Old (still works via backward compatibility)
from src.pipeline.llm.groq_client import call_llm

# New (recommended)
from src.pipeline.llm import call_llm

# Text utilities (previously private in groq_client.py)
from src.pipeline.llm import extract_date, to_cents, extract_number
```
