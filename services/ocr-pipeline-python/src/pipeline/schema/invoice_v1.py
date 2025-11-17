"""Pydantic models describing the target invoice_v1 contract."""

from __future__ import annotations

from typing import List, Optional
from pydantic import BaseModel, Field, validator


class Invoice(BaseModel):
    invoice_number: Optional[str] = None
    invoice_date: str
    vendor_name: str
    vendor_tax_id: Optional[str] = None
    buyer_name: Optional[str] = None
    currency_code: str
    subtotal_cents: Optional[int] = None
    tax_cents: Optional[int] = None
    total_cents: int
    discount_cents: int = 0

    @validator("invoice_date", pre=True, always=True)
    def normalize_date(cls, value):  # noqa: N805
        if value in (None, "", "null"):
            return None
        return value

    @validator("discount_cents", pre=True, always=True)
    def normalize_discount(cls, value):  # noqa: N805
        if value in (None, "", "null"):
            return 0
        try:
            parsed = int(float(value))
        except (TypeError, ValueError):
            return 0
        return max(parsed, 0)


class Item(BaseModel):
    idx: int
    description: str
    qty: float = 1.0
    unit_price_cents: Optional[int] = None
    line_total_cents: int
    category: Optional[str] = None


class Notes(BaseModel):
    warnings: Optional[List[str]] = None
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)


class InvoiceV1(BaseModel):
    schema_version: str = Field(default="invoice_v1")
    invoice: Invoice
    items: List[Item]
    notes: Optional[Notes] = None


def validate_invoice_payload(payload: dict) -> InvoiceV1:
    return InvoiceV1.model_validate(payload)
