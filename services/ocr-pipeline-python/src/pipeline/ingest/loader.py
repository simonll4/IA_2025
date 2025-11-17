from pathlib import Path
import mimetypes


def detect_source(path: str) -> str:
    """Detect if the file is a PDF or an image"""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"File not found: {path}")

    # Check by extension first
    if p.suffix.lower() == ".pdf":
        return "pdf"

    # Check by mimetype for images
    mime, _ = mimetypes.guess_type(str(p))
    if mime and mime.startswith("image/"):
        return "image"

    # Default fallback for common image extensions
    if p.suffix.lower() in [
        ".jpg",
        ".jpeg",
        ".png",
        ".bmp",
        ".tiff",
        ".tif",
        ".gif",
        ".webp",
    ]:
        return "image"

    # Treat unknown formats as images so the downstream OCR path gets a chance.
    return "image"  # Default assumption
