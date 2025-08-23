"""Upload providers for Google Photos Explorer.

This module defines a simple storage abstraction and implements an
Azure Blob Storage provider. The design is intentionally generic so that
other providers (e.g., S3, GCS) can be added later.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Optional, Protocol, Tuple

from .config import ConfigManager

try:
    # Lazy import to avoid hard dependency unless used
    from azure.storage.blob import BlobServiceClient, ContentSettings
except Exception:  # pragma: no cover - the dependency may not be installed yet
    BlobServiceClient = None  # type: ignore
    ContentSettings = None  # type: ignore


class StorageProvider(Protocol):
    """Protocol for upload providers."""

    def upload_bytes(  # noqa: E704
        self,
        data: bytes,
        destination_path: str,
        *,
        content_type: Optional[str] = None,
        metadata: Optional[Dict[str, str]] = None,
    ) -> None: ...

    def upload_stream(  # noqa: E704
        self,
        stream: io.BufferedReader,
        destination_path: str,
        *,
        content_type: Optional[str] = None,
        metadata: Optional[Dict[str, str]] = None,
    ) -> None: ...


@dataclass
class UploadTarget:
    provider: str  # e.g., "azure"
    container: Optional[str] = None
    prefix: str = ""


class AzureBlobStorageProvider:
    """Azure Blob Storage implementation of StorageProvider."""

    def __init__(self, connection_string: str, container_name: str):
        if BlobServiceClient is None:
            raise RuntimeError("azure-storage-blob is required. Add it to requirements and install.")
        self._client = BlobServiceClient.from_connection_string(connection_string)
        self._container = self._client.get_container_client(container_name)
        # Ensure container exists
        try:
            self._container.create_container()
        except Exception:
            pass  # already exists or insufficient permissions

    def upload_bytes(
        self,
        data: bytes,
        destination_path: str,
        *,
        content_type: Optional[str] = None,
        metadata: Optional[Dict[str, str]] = None,
    ) -> None:
        blob_client = self._container.get_blob_client(destination_path)
        content_settings = ContentSettings(content_type=content_type) if content_type else None
        blob_client.upload_blob(data, overwrite=True, content_settings=content_settings, metadata=metadata)

    def upload_stream(
        self,
        stream: io.BufferedReader,
        destination_path: str,
        *,
        content_type: Optional[str] = None,
        metadata: Optional[Dict[str, str]] = None,
    ) -> None:
        blob_client = self._container.get_blob_client(destination_path)
        content_settings = ContentSettings(content_type=content_type) if content_type else None
        blob_client.upload_blob(stream, overwrite=True, content_settings=content_settings, metadata=metadata)


def detect_content_type(filename: str) -> Optional[str]:
    ext = Path(filename).suffix.lower()
    # Minimal mapping; Azure determines type from content_settings
    mapping = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".bmp": "image/bmp",
        ".webp": "image/webp",
        ".heic": "image/heic",
        ".mp4": "video/mp4",
        ".mov": "video/quicktime",
        ".avi": "video/x-msvideo",
        ".wmv": "video/x-ms-wmv",
        ".m4v": "video/x-m4v",
        ".mpg": "video/mpeg",
        ".mpeg": "video/mpeg",
        ".json": "application/json",
    }
    return mapping.get(ext)


def _sanitize_segment(segment: str) -> str:
    """Sanitize a single path segment for Azure blob compatibility.

    - Trim leading/trailing whitespace
    - Replace disallowed characters with '_'
    - Avoid trailing dots or spaces
    - Keep common readable chars: letters, numbers, space, dash, underscore,
      dot, parentheses
    - Ensure non-empty segment
    """
    import re

    cleaned = segment.strip()
    if not cleaned:
        return "_"
    # Replace backslashes entirely; they are path separators on Windows
    cleaned = cleaned.replace("\\", "/")
    # Only allow a safe subset per segment
    cleaned = re.sub(r"[^A-Za-z0-9 ._\-()]", "_", cleaned)
    # Remove trailing dots/spaces which can cause trouble
    cleaned = cleaned.rstrip(" .") or "_"
    # Azure suggests max segment length; keep it reasonable
    if len(cleaned) > 255:
        cleaned = cleaned[:255]
    return cleaned


def sanitize_blob_path(path: str) -> str:
    """Sanitize a full blob path by cleaning each segment and normalizing slashes."""
    # Normalize separators and split into segments
    parts = [p for p in path.replace("\\", "/").split("/") if p not in ("", ".")]
    safe_parts = [_sanitize_segment(p) for p in parts]
    return "/".join(safe_parts)


def build_provider(config: ConfigManager, target: Optional[UploadTarget] = None) -> Tuple[StorageProvider, str]:
    """Build a provider based on config and target.

    Returns a tuple of (provider, prefix).
    """
    target = target or UploadTarget(provider="azure")
    if target.provider != "azure":
        raise ValueError("Only 'azure' provider is supported at this time")

    connection_string = config.get_azure_connection_string()
    container = target.container or config.get_azure_container()
    if not connection_string or not container:
        raise ValueError("Azure is not configured. Set connection string and container.")

    # Validate container name according to Azure rules
    def _validate_container_name(name: str) -> None:
        import re

        original = name
        name = name.strip().strip('"').strip("'")
        if original != name:
            # If quotes were present, treat as invalid and provide guidance
            msg = (
                "Azure container name appears quoted: "
                f"{original}. Remove quotes and try again (e.g., --container mycontainer)."
            )
            raise ValueError(msg)
        if not (3 <= len(name) <= 63):
            raise ValueError("Azure container name must be between 3 and 63 characters.")
        if not re.fullmatch(r"[a-z0-9-]+", name):
            raise ValueError("Azure container name must use only lowercase letters, numbers, and hyphens (-).")
        if not (name[0].isalnum() and name[-1].isalnum()):
            raise ValueError("Azure container name must start and end with a letter or number.")

    _validate_container_name(container)

    provider = AzureBlobStorageProvider(connection_string, container)
    prefix = target.prefix or config.get_azure_default_prefix()
    if prefix and not prefix.endswith("/"):
        prefix = prefix + "/"
    return provider, prefix


def upload_files(
    files: Iterable[Tuple[Path, str, bytes | None, Dict[str, Any]]],
    *,
    provider: StorageProvider,
    prefix: str = "",
    include_metadata: bool = True,
    progress: Optional[Callable[[int, int, str], None]] = None,
) -> Dict[str, Any]:
    """Upload a list of files.

    Each item in files is a tuple of (zip_path, archive_path, raw_bytes_or_none, metadata_dict).
    If raw_bytes_or_none is None, caller will provide a stream when calling this function.
    """
    total = 0
    uploaded = 0
    skipped = 0
    errors = 0
    details = []

    iterable = list(files)
    total = len(iterable)
    for idx, (zip_path, archive_path, raw_bytes, metadata) in enumerate(iterable, 1):
        dest = prefix + archive_path.replace("\\", "/")
        content_type = detect_content_type(archive_path)
        try:
            if progress:
                progress(idx, total, archive_path)
            md = None
            if include_metadata and metadata:
                # Flatten metadata to string values where possible
                md = {k: str(v) for k, v in metadata.items() if isinstance(k, str)}
            if raw_bytes is not None:
                provider.upload_bytes(raw_bytes, dest, content_type=content_type, metadata=md)
            else:
                # Caller must pass a stream if raw_bytes is None; open from disk is not available here
                # For this project, raw_bytes will always be provided by reading from the zip
                provider.upload_bytes(b"", dest, content_type=content_type, metadata=md)
            uploaded += 1
            details.append({"path": archive_path, "destination": dest, "status": "uploaded"})
        except Exception as e:
            errors += 1
            details.append({"path": archive_path, "destination": dest, "status": "error", "error": str(e)})

    return {
        "total": total,
        "uploaded": uploaded,
        "skipped": skipped,
        "errors": errors,
        "details": details,
    }
