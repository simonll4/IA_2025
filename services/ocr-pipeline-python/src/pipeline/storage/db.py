"""Persistence helpers for invoice_v1 records."""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

from loguru import logger
from sqlalchemy import (
    Column,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
    select,
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
from sqlalchemy import text

from src.pipeline.config.settings import DB_URL

Base = declarative_base()


class Document(Base):
    __tablename__ = "invoices"

    id = Column(Integer, primary_key=True)
    path = Column(String, nullable=False)
    file_hash = Column(String, nullable=True, unique=True, index=True)
    raw_text = Column(Text, nullable=False)
    raw_json = Column(Text, nullable=False)

    invoice_number = Column(String, nullable=True)
    invoice_date = Column(String, nullable=False)
    vendor_name = Column(String, nullable=False)
    vendor_tax_id = Column(String, nullable=True)
    buyer_name = Column(String, nullable=True)
    currency_code = Column(String, nullable=False)
    subtotal_cents = Column(Integer, nullable=True)
    tax_cents = Column(Integer, nullable=True)
    total_cents = Column(Integer, nullable=False)
    discount_cents = Column(Integer, nullable=False, default=0)

    confidence = Column(Float, nullable=True)
    warnings = Column(Text, nullable=True)

    items = relationship(
        "InvoiceItem", cascade="all, delete-orphan", back_populates="document"
    )


class InvoiceItem(Base):
    __tablename__ = "items"

    id = Column(Integer, primary_key=True)
    document_id = Column(Integer, ForeignKey("invoices.id"), nullable=False)
    idx = Column(Integer, nullable=False)
    description = Column(Text, nullable=False)
    qty = Column(Float, nullable=False)
    unit_price_cents = Column(Integer, nullable=True)
    line_total_cents = Column(Integer, nullable=False)
    category = Column(String, nullable=True)

    document = relationship("Document", back_populates="items")


# Configure the shared engine/session factory used across the service layer.
engine = create_engine(DB_URL, future=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def init_db() -> None:
    """
    Initialize the database by creating all tables.
    
    Also ensures the database file and directory have proper permissions
    for write operations.
    """
    try:
        # Ensure database directory exists and is writable
        if DB_URL.startswith("sqlite:///"):
            db_path = DB_URL.replace("sqlite:///", "")
            db_file = Path(db_path)
            db_dir = db_file.parent
            
            # Create directory if it doesn't exist
            db_dir.mkdir(parents=True, exist_ok=True)
            
            # Check if directory is writable
            if not os.access(db_dir, os.W_OK):
                logger.warning(
                    f"Database directory {db_dir} is not writable. "
                    "This may cause write errors."
                )
            
            # If database file exists, check if it's writable
            if db_file.exists() and not os.access(db_file, os.W_OK):
                logger.warning(
                    f"Database file {db_file} exists but is read-only. "
                    "Attempting to fix permissions..."
                )
                try:
                    os.chmod(db_file, 0o666)
                    logger.info(f"Fixed permissions on {db_file}")
                except Exception as e:
                    logger.error(f"Could not fix permissions on {db_file}: {e}")
        
        # Create all tables
        Base.metadata.create_all(engine)
        logger.info("Database initialized successfully")
        
    except Exception as e:
        logger.error(f"Error initializing database: {e}")
        raise


init_db()


def _ensure_discount_column() -> None:
    with engine.connect() as conn:
        result = conn.execute(text("PRAGMA table_info(invoices)"))
        columns = {row[1] for row in result}
        if "discount_cents" not in columns:
            conn.execute(
                text(
                    "ALTER TABLE invoices "
                    "ADD COLUMN discount_cents INTEGER NOT NULL DEFAULT 0"
                )
            )


_ensure_discount_column()


@contextmanager
def session_scope():
    # Unit-of-work helper so callers don't forget to commit/rollback sessions.
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:  # noqa: BLE001
        session.rollback()
        raise
    finally:
        session.close()


def get_document_by_hash(file_hash: Optional[str]) -> Optional[dict]:
    # Basic caching layer: reuse previous LLM results for identical uploads.
    if not file_hash:
        return None
    with session_scope() as session:
        result = session.execute(
            select(Document).where(Document.file_hash == file_hash)
        ).scalar_one_or_none()
        if not result:
            return None
        return json.loads(result.raw_json)


def save_document(
    path: str, file_hash: Optional[str], raw_text: str, payload: dict
) -> int:
    # Persist both the denormalised JSON and the structured tables for querying/reporting.
    warnings = None
    confidence = None
    notes = payload.get("notes")
    if isinstance(notes, dict):
        warnings = json.dumps(notes.get("warnings")) if notes.get("warnings") else None
        confidence = notes.get("confidence")

    invoice = payload["invoice"]

    with session_scope() as session:
        doc = Document(
            path=path,
            file_hash=file_hash,
            raw_text=raw_text,
            raw_json=json.dumps(payload, ensure_ascii=False),
            invoice_number=invoice.get("invoice_number"),
            invoice_date=invoice["invoice_date"],
            vendor_name=invoice["vendor_name"],
            vendor_tax_id=invoice.get("vendor_tax_id"),
            buyer_name=invoice.get("buyer_name"),
            currency_code=invoice["currency_code"],
            subtotal_cents=invoice.get("subtotal_cents"),
            tax_cents=invoice.get("tax_cents"),
            total_cents=invoice["total_cents"],
            discount_cents=invoice.get("discount_cents", 0),
            confidence=confidence,
            warnings=warnings,
        )
        session.add(doc)
        session.flush()

        for item in payload.get("items", []):
            session.add(
                InvoiceItem(
                    document_id=doc.id,
                    idx=item["idx"],
                    description=item["description"],
                    qty=item.get("qty", 1.0),
                    unit_price_cents=item.get("unit_price_cents"),
                    line_total_cents=item["line_total_cents"],
                    category=item.get("category"),
                )
            )

        logger.info("Persisted document {}", doc.id)
        return doc.id
