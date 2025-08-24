"""Thumbnail generation utilities.

This module provides a helper to generate image thumbnails from raw bytes.
"""

from __future__ import annotations

import io
from typing import Optional, Tuple

SUPPORTED_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}


def _ext_to_pil_format(ext: str) -> Optional[str]:
    ext = ext.lower()
    mapping = {
        ".jpg": "JPEG",
        ".jpeg": "JPEG",
        ".png": "PNG",
        ".gif": "GIF",
        ".bmp": "BMP",
        ".webp": "WEBP",
    }
    return mapping.get(ext)


def _ext_to_content_type(ext: str) -> Optional[str]:
    ext = ext.lower()
    mapping = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".bmp": "image/bmp",
        ".webp": "image/webp",
    }
    return mapping.get(ext)


def generate_thumbnail(
    image_bytes: bytes,
    *,
    original_ext: str,
    max_size: Tuple[int, int] = (512, 512),
) -> Tuple[bytes, Optional[str]]:
    """Create a thumbnail for an image.

    Args:
        image_bytes: Raw image bytes
        original_ext: File extension including dot (e.g., ".jpg")
        max_size: Max (width, height) for the thumbnail box

    Returns:
        (thumbnail_bytes, content_type)

    Raises:
        RuntimeError if Pillow is not installed.
    """
    try:
        from PIL import Image
    except Exception as e:  # pragma: no cover - environment dependency
        raise RuntimeError("Pillow is required for thumbnail generation. Install 'Pillow'.") from e

    pil_format = _ext_to_pil_format(original_ext)
    if pil_format is None:
        # Unsupported format for output (e.g., .heic). Let caller decide to skip.
        return b"", None

    with Image.open(io.BytesIO(image_bytes)) as img:
        # Ensure a deterministic mode for formats that do not support alpha
        if pil_format == "JPEG":
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
        # Resize in-place preserving aspect ratio
        img.thumbnail(max_size, Image.LANCZOS)

        out = io.BytesIO()
        save_kwargs = {}
        if pil_format == "JPEG":
            save_kwargs.update({"quality": 85, "optimize": True, "progressive": True})
        if pil_format == "WEBP":
            save_kwargs.update({"quality": 80})
        img.save(out, format=pil_format, **save_kwargs)
        thumb_bytes = out.getvalue()
        content_type = _ext_to_content_type(original_ext)
        return thumb_bytes, content_type
