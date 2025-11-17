"""File utility helpers for the pipeline module.

Currently provides streaming-safe hashing for cache keys.
"""

import hashlib
from typing import Optional


def compute_file_hash(path: str, chunk_size: int = 1024 * 1024) -> Optional[str]:
    """Compute a SHA-256 hex digest for a file by streaming its contents.

    Args:
        path: Absolute or relative path to the file.
        chunk_size: Size of chunks to read to avoid loading the whole file.

    Returns:
        Hexadecimal SHA-256 digest string, or None if hashing fails.
    """
    try:
        # Stream the file so large uploads do not exhaust memory while hashing.
        h = hashlib.sha256()
        with open(path, "rb") as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None
