"""
Pipeline API Endpoints

This module provides the HTTP interface for invoice OCR and extraction.

Endpoints:
- POST /api/pipeline/extract → Upload and process invoice file

Features:
- Concurrency control (semaphore-based)
- File type validation (PDF, JPG, PNG, BMP)
- Async file processing
- Error handling with detailed messages

Supported Formats:
- PDF (up to 5 pages by default)
- Images: JPG, PNG, BMP
"""

import asyncio
import os
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from src.pipeline.config.settings import UPLOAD_DIR
from src.pipeline.service.pipeline import run_pipeline

router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])

# Concurrency control - prevent overwhelming the LLM API
_semaphore = asyncio.Semaphore(int(os.getenv("MAX_CONCURRENCY", "1")))


@router.post("/extract")
async def extract_document(file: UploadFile = File(...)) -> JSONResponse:
    """
    Process an invoice PDF or image and return structured data.

    This endpoint:
    1. Validates file type
    2. Saves uploaded file with unique ID
    3. Runs OCR + LLM extraction pipeline
    4. Returns structured JSON (invoice_v1 schema)
    5. Keeps successfully processed files on disk
    
    Supported File Types:
    - application/pdf
    - image/jpeg, image/jpg
    - image/png
    - image/bmp
    
    Args:
        file: Uploaded file (multipart/form-data)
        
    Returns:
        JSONResponse: Structured invoice data
        
    Raises:
        HTTPException 400: Unsupported file type
        HTTPException 500: Processing error
        
    Example Response:
    {
        "schema_version": "invoice_v1",
        "invoice": {
            "vendor_name": "ACME Corp",
            "total_cents": 10000,
            ...
        },
        "items": [...]
    }
    """
    # File type validation
    allowed_types = {
        "application/pdf",
        "image/jpeg",
        "image/jpg",
        "image/png",
        "image/bmp",
    }

    if file.content_type not in allowed_types:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported file type: {file.content_type}. "
                "Allowed: PDF, JPG, PNG, BMP"
            ),
        )

    # Generate unique filename and save upload
    file_id = str(uuid4())
    original_ext = Path(file.filename or "unknown").suffix.lower() or ".pdf"
    stored_path = UPLOAD_DIR / f"{file_id}{original_ext}"
    cleanup_file = True

    try:
        # Save file to disk
        content = await file.read()
        stored_path.write_bytes(content)

        # Run pipeline with concurrency control
        # This prevents overwhelming the LLM API with parallel requests
        async with _semaphore:
            result = await asyncio.to_thread(run_pipeline, str(stored_path))

        # Keep successfully processed uploads for debugging/audit
        cleanup_file = False

        return JSONResponse(content=result)

    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Pipeline execution failed: {str(e)}"
        )
    finally:
        # Clean up only if processing failed
        if cleanup_file and stored_path.exists():
            stored_path.unlink()
