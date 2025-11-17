"""Unified text extraction for PDFs and images using pdfminer + Tesseract."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List
import io

import numpy as np
from loguru import logger
from pdf2image import convert_from_path
from pdfminer.high_level import extract_text_to_fp
from pdfminer.layout import LAParams
from PIL import Image
import pytesseract
from src.pipeline.config.settings import PDF_OCR_DPI


@dataclass
class PageText:
    page: int
    lines: List[str]

    def join(self) -> str:
        return "\n".join(self.lines)


def _clean_lines(raw: str) -> List[str]:
    # Normalize pdfminer/pytesseract output by removing blank lines and trimming whitespace.
    return [line.strip() for line in raw.splitlines() if line.strip()]


def extract_pdf_text(path: str, max_pages: int | None = None) -> List[PageText]:
    # First attempt: structured extraction via pdfminer; fall back to OCR if the signal is weak.
    laparams = LAParams(line_margin=0.2, word_margin=0.1, char_margin=1.0)
    with open(path, "rb") as fp:
        buffer = io.StringIO()
        extract_text_to_fp(fp, buffer, laparams=laparams, output_type="text")
    buffer.seek(0)
    content = buffer.read()

    parts = content.split("\f") if content else []
    pages = [
        PageText(page=idx, lines=_clean_lines(part))
        for idx, part in enumerate(parts, start=1)
        if part.strip()
    ]

    total_len = sum(len(" ".join(p.lines)) for p in pages)
    if total_len >= 200:
        return pages

    logger.info("PDF text too short, falling back to OCR")
    pil_pages = convert_from_path(path, dpi=PDF_OCR_DPI)
    if max_pages:
        pil_pages = pil_pages[:max_pages]
    return [_ocr_page(img, idx + 1) for idx, img in enumerate(pil_pages)]


def extract_image_text(path: str) -> List[PageText]:
    img = Image.open(path)
    return [_ocr_page(img, 1)]


OCR_CONFIG = "--psm 6 -c preserve_interword_spaces=1"


def _ocr_page(image: Image.Image, page_number: int) -> PageText:
    # Apply lightweight preprocessing before handing the bitmap to Tesseract.
    gray = image.convert("L")
    np_img = np.array(gray)
    processed = _binarize(np_img)
    text = pytesseract.image_to_string(processed, lang="eng", config=OCR_CONFIG)
    lines = _clean_lines(text)
    logger.debug(
        "OCR page {num} extracted {count} lines", num=page_number, count=len(lines)
    )
    return PageText(page=page_number, lines=lines)


def _binarize(img: np.ndarray) -> Image.Image:
    # Simple thresholding keeps the OCR stack deterministic and dependency-free.
    if img.dtype != np.uint8:
        img = img.astype(np.uint8)
    thresh = 200
    binary = (img > thresh).astype(np.uint8) * 255
    return Image.fromarray(binary)


def join_pages(pages: List[PageText]) -> str:
    # Annotate each page so downstream prompts retain pagination context.
    sections = []
    for page in pages:
        sections.append(f"=== Page {page.page} ===\n" + page.join())
    return "\n".join(sections)
