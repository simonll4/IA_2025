#!/usr/bin/env python3
"""
Cache Management Script for Invoice Processing Platform

This script provides utilities to clear cached invoice data from the SQLite database.
Caching is used to avoid redundant LLM API calls for identical files (based on file hash).

Usage:
    # Clear entire database
    python clear_cache.py --all

    # Delete specific invoice by number
    python clear_cache.py --invoice 95611677

    # Delete by file path/hash
    python clear_cache.py --file path/to/invoice.pdf

When to Clear Cache:
- After code changes to extraction logic
- After prompt modifications
- Before running end-to-end tests
- When debugging with known test files

Why Cache Exists:
- Saves LLM API costs (avoid reprocessing identical files)
- Faster responses for duplicate uploads
- Based on MD5 file hash (Document.file_hash column)
"""

import argparse
import sqlite3
import sys
from pathlib import Path

# Add service directory to path for imports (ocr-pipeline-python)
PROJECT_ROOT = Path(__file__).parent
OCR_SERVICE_ROOT = PROJECT_ROOT / "services" / "ocr-pipeline-python"

sys.path.insert(0, str(OCR_SERVICE_ROOT))

from src.pipeline.storage import db
from src.pipeline.utils.files import compute_file_hash


# ============================================================================
# CACHE CLEARING FUNCTIONS
# ============================================================================


def clear_all_cache():
    """
    Delete entire database file.

    This removes all cached invoices and forces re-extraction on next run.
    Use when you want a completely fresh start.
    """
    db_path = Path("data/app.db")
    if db_path.exists():
        db_path.unlink()
        print("✅ Complete cache cleared (data/app.db deleted)")
    else:
        print("ℹ️  No cache to clear")


def clear_by_invoice_number(invoice_number: str):
    """
    Delete cache for specific invoice by invoice number.

    Removes from both Document and invoices tables.
    Use when you want to re-extract a specific invoice.

    Args:
        invoice_number: Invoice number to delete (e.g., "95611677")
    """
    # Clean from Document table
    with db.session_scope() as s:
        deleted_docs = (
            s.query(db.Document)
            .filter(
                db.Document.raw_json.like(f'%"invoice_number": "{invoice_number}"%')
            )
            .delete(synchronize_session=False)
        )

    # Clean from invoices table
    conn = sqlite3.connect("data/app.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM invoices WHERE invoice_number = ?", (invoice_number,))
    deleted_inv = cursor.rowcount
    conn.commit()
    conn.close()

    print(
        f"✅ Deleted {deleted_docs} Document entries and {deleted_inv} invoice entries for #{invoice_number}"
    )


def clear_by_file(file_path: str):
    """
    Delete cache for specific file by computing its hash.

    Use when you want to re-extract a specific file.

    Args:
        file_path: Path to invoice file (e.g., "datasets/invoice.pdf")
    """
    file_hash = compute_file_hash(file_path)

    with db.session_scope() as s:
        deleted = (
            s.query(db.Document).filter(db.Document.file_hash == file_hash).delete()
        )

    print(f"✅ Deleted {deleted} entries for file: {file_path}")
    print(f"   File hash: {file_hash}")


# ============================================================================
# CLI INTERFACE
# ============================================================================


def main():
    """Parse arguments and execute cache clearing operation."""
    parser = argparse.ArgumentParser(
        description="Clear invoice processing cache",
        epilog="Example: python clear_cache.py --invoice 95611677",
    )
    parser.add_argument(
        "--all", action="store_true", help="Delete entire cache (data/app.db)"
    )
    parser.add_argument("--invoice", type=str, help="Delete specific invoice by number")
    parser.add_argument("--file", type=str, help="Delete specific file by path")

    args = parser.parse_args()

    # Execute requested operation
    if args.all:
        clear_all_cache()
    elif args.invoice:
        clear_by_invoice_number(args.invoice)
    elif args.file:
        clear_by_file(args.file)
    else:
        # Show help if no arguments provided
        parser.print_help()
        print("\n💡 Examples:")
        print("  python clear_cache.py --all")
        print("  python clear_cache.py --invoice 40378170")
        print("  python clear_cache.py --file data/uploads/abc.png")


if __name__ == "__main__":
    main()
