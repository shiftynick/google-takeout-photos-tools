"""Core Google Photos Explorer functionality."""

import json
import os
import re
import zipfile
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from .config import ConfigManager
from .thumbnail import generate_thumbnail
from .upload import UploadTarget, build_provider, detect_content_type, sanitize_blob_path


class GooglePhotosExplorer:
    """Core class for exploring Google Photos Takeout zip files."""

    def __init__(self, zip_directory: str, preload_catalog: bool = False, catalog_progress_callback=None):
        self.zip_directory = Path(zip_directory)
        self.zip_files = self._find_zip_files()
        self._cache = {}
        if preload_catalog:
            # Eagerly build the album/media catalog to avoid first-call latency
            self._ensure_catalog(progress_callback=catalog_progress_callback)

    def _map_zips_parallel(
        self,
        worker: Callable[[Path], Any],
        progress_callback=None,
        max_workers: Optional[int] = None,
    ) -> List[Tuple[Path, Any]]:
        """Run a worker over all zip files in parallel.

        Args:
            worker: Function taking a Path to a zip and returning a result.
            progress_callback: Optional callback (completed, total)
            max_workers: Optional cap for the pool size

        Returns:
            List of (zip_path, result) ordered by original zip order.
        """
        total = len(self.zip_files)
        if total == 0:
            return []

        pool_size = max_workers or min(32, (os.cpu_count() or 4) * 2, total)
        collected: List[Tuple[int, Path, Any]] = []

        with ThreadPoolExecutor(max_workers=pool_size) as executor:
            future_to_info = {}
            for idx, zip_path in enumerate(self.zip_files, 1):
                fut = executor.submit(worker, zip_path)
                future_to_info[fut] = (idx, zip_path)

            completed = 0
            for fut in as_completed(future_to_info):
                idx, zip_path = future_to_info[fut]
                res = fut.result()
                collected.append((idx, zip_path, res))
                completed += 1
                if progress_callback:
                    progress_callback(completed, total)

        # Return results in the original order
        ordered = [(zp, res) for (idx, zp, res) in sorted(collected, key=lambda t: t[0])]
        return ordered

    def _find_zip_files(self) -> List[Path]:
        """Find all zip files in the specified directory."""
        if not self.zip_directory.exists():
            raise ValueError(f"Directory {self.zip_directory} does not exist")

        zip_files = sorted(self.zip_directory.glob("*.zip"))
        if not zip_files:
            raise ValueError(f"No zip files found in {self.zip_directory}")

        return zip_files

    def _ensure_catalog(self, progress_callback=None, force_refresh: bool = False) -> Dict[str, Any]:
        """Build and cache a catalog of albums and media across all zips.

        Catalog structure:
            {
              "by_zip": { Path(zip): [file_name, ...] },
              "by_album": {
                  album_name: {
                      "files": [(zip_path, file_path), ...],
                      "direct_media": [(zip_path, file_path), ...],
                      "info_file": Optional[(zip_path, file_path)],
                      "supplemental_map": { photo_name: (zip_path, json_path) }
                  },
              },
              "media_by_basename": { basename: [(zip_path, file_path), ...] }
            }
        """
        if not force_refresh and "album_catalog" in self._cache:
            return self._cache["album_catalog"]

        image_exts = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".heic"}
        video_exts = {".mp4", ".mov", ".avi", ".wmv", ".m4v", ".mpg", ".mpeg"}

        by_zip: Dict[Path, List[str]] = {}
        by_album: Dict[str, Dict[str, Any]] = {}
        media_by_basename: Dict[str, List[Tuple[Path, str]]] = {}

        def worker(zp: Path) -> List[str]:
            with zipfile.ZipFile(zp, "r") as zf:
                return zf.namelist()

        for zip_path, names in self._map_zips_parallel(worker, progress_callback=progress_callback):
            by_zip[zip_path] = names
            for file_name in names:
                p = Path(file_name)
                base = p.name
                ext = p.suffix.lower()

                # Index global media by basename
                if ext in image_exts or ext in video_exts:
                    media_by_basename.setdefault(base, []).append((zip_path, file_name))

                # Index by album
                parts = file_name.split("/")
                if len(parts) >= 3 and parts[0] == "Takeout" and parts[1] == "Google Photos":
                    album_name = parts[2]
                    album = by_album.setdefault(
                        album_name,
                        {
                            "files": [],
                            "direct_media": [],
                            "info_file": None,
                            "supplemental_map": {},  # photo_name -> (zip_path, json_path)
                        },
                    )
                    album["files"].append((zip_path, file_name))

                    if file_name.endswith("metadata.json") and parts[-1] == "metadata.json":
                        album["info_file"] = (zip_path, file_name)

                    if ext in image_exts or ext in video_exts:
                        album["direct_media"].append((zip_path, file_name))

                    if file_name.endswith(".supplemental-metadata.json"):
                        photo_name = base.replace(".supplemental-metadata.json", "")
                        # Prefer first seen mapping; do not overwrite if duplicates
                        album["supplemental_map"].setdefault(photo_name, (zip_path, file_name))

        catalog = {"by_zip": by_zip, "by_album": by_album, "media_by_basename": media_by_basename}
        self._cache["album_catalog"] = catalog
        return catalog

    def _get_album_data(self, album_name: str) -> Optional[Dict[str, Any]]:
        catalog = self._ensure_catalog()
        return catalog["by_album"].get(album_name)

    def build_catalog(self, progress_callback=None, force_refresh: bool = False) -> Dict[str, Any]:
        """Public API: build (or fetch) the cached album/media catalog."""
        return self._ensure_catalog(progress_callback=progress_callback, force_refresh=force_refresh)

    def clear_catalog_cache(self) -> None:
        """Public API: clear the cached album/media catalog."""
        if "album_catalog" in self._cache:
            del self._cache["album_catalog"]

    def list_zips(self) -> List[Dict[str, Any]]:
        """List all zip files found.

        Returns:
            List of dicts with zip file information
        """

        def worker(zp: Path) -> float:
            try:
                return zp.stat().st_size / (1024 * 1024)
            except Exception:
                return 0.0

        results: List[Dict[str, Any]] = []
        for idx, (zip_path, size_mb) in enumerate(self._map_zips_parallel(worker), 1):
            results.append({"index": idx, "name": zip_path.name, "path": zip_path, "size_mb": size_mb})
        return results

    def explore_zip(self, zip_index: int) -> Optional[Dict[str, Any]]:
        """Explore contents of a specific zip file.

        Returns:
            Dictionary with zip contents information or None if invalid index
        """
        if zip_index < 1 or zip_index > len(self.zip_files):
            return None

        zip_path = self.zip_files[zip_index - 1]

        catalog = self._ensure_catalog()
        file_list = catalog["by_zip"].get(zip_path, [])

        # Categorize files
        images = []
        videos = []
        json_files = []
        other = []

        image_exts = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".heic"}
        video_exts = {".mp4", ".mov", ".avi", ".wmv", ".m4v", ".mpg", ".mpeg"}

        for file_name in file_list:
            ext = Path(file_name).suffix.lower()
            if ext in image_exts:
                images.append(file_name)
            elif ext in video_exts:
                videos.append(file_name)
            elif ext == ".json":
                json_files.append(file_name)
            else:
                other.append(file_name)

        return {
            "zip_name": zip_path.name,
            "zip_path": zip_path,
            "total_files": len(file_list),
            "images": images,
            "videos": videos,
            "json_files": json_files,
            "other": other,
            "counts": {"images": len(images), "videos": len(videos), "json": len(json_files), "other": len(other)},
            "sample_files": file_list[:10],
        }

    def search_files(self, pattern: str, progress_callback=None) -> Dict[str, List[str]]:
        """Search for files matching a pattern across all zips.

        Args:
            pattern: Regex pattern to search for
            progress_callback: Optional callback for progress updates

        Returns:
            Dictionary mapping zip names to lists of matching files
        """
        regex = re.compile(pattern, re.IGNORECASE)
        results: Dict[str, List[str]] = {}

        catalog = self._ensure_catalog()
        by_zip: Dict[Path, List[str]] = catalog["by_zip"]

        total = len(self.zip_files)
        for idx, zip_path in enumerate(self.zip_files, 1):
            names = by_zip.get(zip_path, [])
            matches = [fn for fn in names if regex.search(fn)]
            if matches:
                results[zip_path.name] = matches
            if progress_callback:
                progress_callback(idx, total)

        return results

    def extract_metadata(self, filename_pattern: str, progress_callback=None) -> List[Dict]:
        """Extract metadata from JSON files matching a pattern.

        Returns:
            List of metadata dictionaries
        """
        regex = re.compile(filename_pattern, re.IGNORECASE)
        all_metadata: List[Dict[str, Any]] = []

        catalog = self._ensure_catalog()
        by_zip: Dict[Path, List[str]] = catalog["by_zip"]

        total = len(self.zip_files)
        for idx, zip_path in enumerate(self.zip_files, 1):
            names = by_zip.get(zip_path, [])
            json_candidates = [fn for fn in names if fn.endswith(".json") and regex.search(fn)]
            if json_candidates:
                try:
                    with zipfile.ZipFile(zip_path, "r") as zf:
                        for file_name in json_candidates:
                            try:
                                with zf.open(file_name) as f:
                                    metadata = json.load(f)
                                metadata["_source_zip"] = zip_path.name
                                metadata["_source_file"] = file_name
                                all_metadata.append(metadata)
                            except Exception:
                                # Skip corrupted files
                                pass
                except Exception:
                    # If a zip cannot be opened, skip it
                    pass
            if progress_callback:
                progress_callback(idx, total)

        return all_metadata

    def get_date_range(self, progress_callback=None) -> Dict[str, Any]:
        """Analyze date range of photos across all zips.

        Returns:
            Dictionary with date analysis results
        """
        dates: List[int] = []
        errors = 0

        catalog = self._ensure_catalog()
        by_zip: Dict[Path, List[str]] = catalog["by_zip"]

        total = len(self.zip_files)
        for idx, zip_path in enumerate(self.zip_files, 1):
            names = by_zip.get(zip_path, [])
            json_files = [f for f in names if f.endswith(".json")]
            local_errors = 0
            local_dates: List[int] = []
            try:
                with zipfile.ZipFile(zip_path, "r") as zf:
                    for json_file in json_files:
                        try:
                            with zf.open(json_file) as f:
                                metadata = json.load(f)
                            timestamp = None
                            if "photoTakenTime" in metadata:
                                timestamp = metadata["photoTakenTime"].get("timestamp")
                            elif "creationTime" in metadata:
                                timestamp = metadata["creationTime"].get("timestamp")
                            if timestamp:
                                local_dates.append(int(timestamp))
                        except Exception:
                            local_errors += 1
            except Exception:
                local_errors += len(json_files)

            if local_dates:
                dates.extend(local_dates)
            errors += local_errors
            if progress_callback:
                progress_callback(idx, total)

        if dates:
            dates.sort()
            return {
                "total_photos": len(dates),
                "earliest_timestamp": dates[0],
                "latest_timestamp": dates[-1],
                "earliest_date": datetime.fromtimestamp(dates[0]),
                "latest_date": datetime.fromtimestamp(dates[-1]),
                "errors": errors,
            }

        return {"total_photos": 0, "errors": errors}

    def extract_file(self, zip_index: int, file_path: str, output_dir: str = ".") -> bool:
        """Extract a specific file from a zip.

        Returns:
            True if successful, False otherwise
        """
        if zip_index < 1 or zip_index > len(self.zip_files):
            return False

        zip_path = self.zip_files[zip_index - 1]
        output_dir = Path(output_dir)
        output_dir.mkdir(exist_ok=True)

        with zipfile.ZipFile(zip_path, "r") as zf:
            if file_path in zf.namelist():
                zf.extract(file_path, output_dir)
                return True

        return False

    def list_folders(self, progress_callback=None, resolve_references=True) -> Dict[str, Any]:
        """List all unique folders across all zip files with file counts using cached catalog."""
        catalog = self._ensure_catalog(progress_callback=progress_callback)
        by_zip = catalog["by_zip"]
        by_album = catalog["by_album"]

        # Track folders and their file counts
        folder_stats = defaultdict(lambda: {"images": 0, "videos": 0, "json": 0, "other": 0})
        total_files = 0

        image_exts = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".heic"}
        video_exts = {".mp4", ".mov", ".avi", ".wmv", ".m4v", ".mpg", ".mpeg"}

        # Count files directly in folders using cached namelists
        for _zip_path, names in by_zip.items():
            for file_name in names:
                total_files += 1
                folder = str(Path(file_name).parent)
                if folder and folder != ".":
                    ext = Path(file_name).suffix.lower()
                    entry = folder_stats[folder]
                    if ext in image_exts:
                        entry["images"] += 1
                    elif ext in video_exts:
                        entry["videos"] += 1
                    elif ext == ".json":
                        entry["json"] += 1
                    else:
                        entry["other"] += 1

        # Group by album (top-level folders)
        album_folders: Dict[str, Dict[str, int]] = {}
        for folder in folder_stats:
            parts = folder.split("/")
            if len(parts) >= 3 and parts[0] == "Takeout" and parts[1] == "Google Photos":
                album_name = parts[2]
                if album_name not in album_folders:
                    album_folders[album_name] = {
                        "images": 0,
                        "videos": 0,
                        "json": 0,
                        "other": 0,
                        "images_direct": 0,
                        "videos_direct": 0,
                        "images_referenced": 0,
                        "videos_referenced": 0,
                    }
                for key in ["images", "videos", "json", "other"]:
                    album_folders[album_name][key] += folder_stats[folder][key]
                    if key in ["images", "videos"]:
                        album_folders[album_name][f"{key}_direct"] = album_folders[album_name][key]

        # Resolve references using supplemental map from catalog
        if resolve_references:
            for album_name, stats in album_folders.items():
                if stats["json"] > 0 and (stats["images"] + stats["videos"]) < stats["json"] / 2:
                    album = by_album.get(album_name)
                    if not album:
                        continue
                    for photo_name in album["supplemental_map"].keys():
                        ext = Path(photo_name).suffix.lower()
                        if ext in image_exts:
                            album_folders[album_name]["images_referenced"] += 1
                        elif ext in video_exts:
                            album_folders[album_name]["videos_referenced"] += 1

                    album_folders[album_name]["images"] = (
                        album_folders[album_name]["images_direct"] + album_folders[album_name]["images_referenced"]
                    )
                    album_folders[album_name]["videos"] = (
                        album_folders[album_name]["videos_direct"] + album_folders[album_name]["videos_referenced"]
                    )

        return {
            "total_folders": len(folder_stats),
            "total_files": total_files,
            "folder_stats": dict(folder_stats),
            "album_folders": album_folders,
        }

    def get_album_contents(self, album_name: str) -> List[Tuple[str, str]]:
        """Get all files in a specific album across all zips.

        Returns:
            List of tuples (zip_name, file_path)
        """
        album = self._get_album_data(album_name)
        if not album:
            return []
        return [(zp.name, path) for (zp, path) in album["files"]]

    def resolve_album_photos(self, album_name: str) -> Dict[str, List[Tuple[Path, str]]]:
        """Resolve actual photo locations from album metadata using cached catalog.

        Albums often only contain metadata files that reference photos stored elsewhere.
        This method finds the actual photos referenced by the album.

        Returns:
            Dict with 'metadata' and 'photos' lists of (zip_path, file_path) tuples
        """
        catalog = self._ensure_catalog()
        album = catalog["by_album"].get(album_name)
        if not album:
            return {"metadata": [], "photos": []}

        metadata_files: List[Tuple[Path, str]] = list(album["files"])  # Preserve original behavior
        supplemental_map: Dict[str, Tuple[Path, str]] = album["supplemental_map"]
        media_by_basename: Dict[str, List[Tuple[Path, str]]] = catalog["media_by_basename"]

        def read_taken_ts(zp: Path, meta_path: str) -> Optional[int]:
            try:
                with zipfile.ZipFile(zp, "r") as zf:
                    with zf.open(meta_path) as f:
                        meta = json.load(f)
                ts = None
                if isinstance(meta, dict):
                    if "photoTakenTime" in meta and isinstance(meta["photoTakenTime"], dict):
                        ts = meta["photoTakenTime"].get("timestamp")
                    if not ts and "creationTime" in meta and isinstance(meta["creationTime"], dict):
                        ts = meta["creationTime"].get("timestamp")
                return int(ts) if ts else None
            except Exception:
                return None

        # Helper to extract timestamp from a candidate's sibling JSON
        def candidate_timestamp(zp: Path, candidate_path: str) -> Optional[int]:
            try:
                with zipfile.ZipFile(zp, "r") as zf:
                    json_path = f"{candidate_path}.json"
                    if json_path in zf.namelist():
                        with zf.open(json_path) as jf:
                            meta = json.load(jf)
                    else:
                        return None
                ts = None
                if isinstance(meta, dict):
                    if "photoTakenTime" in meta and isinstance(meta["photoTakenTime"], dict):
                        ts = meta["photoTakenTime"].get("timestamp")
                    if not ts and "creationTime" in meta and isinstance(meta["creationTime"], dict):
                        ts = meta["creationTime"].get("timestamp")
                return int(ts) if ts else None
            except Exception:
                return None

        resolved_photos: List[Tuple[Path, str]] = []
        if supplemental_map:
            referenced_info: Dict[str, Dict[str, Any]] = {}
            for photo_name, (zp, mpath) in supplemental_map.items():
                referenced_info[photo_name] = {"taken_ts": read_taken_ts(zp, mpath)}

            for photo_name, ref in referenced_info.items():
                candidates = media_by_basename.get(photo_name, [])
                if not candidates:
                    continue
                if len(candidates) == 1:
                    resolved_photos.append(candidates[0])
                    continue

                taken_ts_ref = ref.get("taken_ts")
                # 1) Prefer JSON timestamp matches (within small tolerance)
                json_matches: List[Tuple[Path, str]] = []
                if taken_ts_ref is not None:
                    for zp, cand in candidates:
                        ts = candidate_timestamp(zp, cand)
                        if ts is not None and abs(int(ts) - int(taken_ts_ref)) <= 2:
                            json_matches.append((zp, cand))
                if len(json_matches) == 1:
                    resolved_photos.append(json_matches[0])
                    continue
                if len(json_matches) > 1:
                    # If more than one JSON match, pick lexicographically smallest path for determinism
                    resolved_photos.append(sorted(json_matches, key=lambda t: t[1])[0])
                    continue

                # 2) Use year hint from referenced timestamp and path segments
                year_matches: List[Tuple[Path, str]] = []
                if taken_ts_ref is not None:
                    try:
                        year_ref = datetime.utcfromtimestamp(int(taken_ts_ref)).year
                    except Exception:
                        year_ref = None
                    if year_ref is not None:
                        for cand in candidates:
                            _, full = cand
                            segments = [p for p in full.split("/") if p]
                            if str(year_ref) in segments:
                                year_matches.append(cand)
                if len(year_matches) == 1:
                    resolved_photos.append(year_matches[0])
                    continue
                if len(year_matches) > 1:
                    resolved_photos.append(sorted(year_matches, key=lambda t: t[1])[0])
                    continue

                # 3) Fallback: deterministic first by full path to avoid missing items
                resolved_photos.append(sorted(candidates, key=lambda t: t[1])[0])

        return {"metadata": metadata_files, "photos": resolved_photos}

    def export_albums(
        self, album_names: List[str], output_dir: str, progress_callback=None, file_progress_callback=None
    ) -> Dict[str, Any]:
        """Export one or more albums to a directory.

        Args:
            album_names: List of album names to export
            output_dir: Directory to export to
            progress_callback: Callback for album progress (current_album, total_albums)
            file_progress_callback: Callback for file progress (current_file, total_files, album_name)

        Returns:
            Dictionary with export statistics
        """
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        stats = {
            "albums_exported": 0,
            "files_exported": 0,
            "errors": 0,
            "skipped": 0,
            "total_size": 0,
            "album_details": {},
        }

        for album_idx, album_name in enumerate(album_names, 1):
            if progress_callback:
                progress_callback(album_idx, len(album_names), album_name)

            album_stats = {"files": 0, "errors": 0, "skipped": 0, "size": 0}

            # Create album directory
            album_dir = output_path / album_name
            album_dir.mkdir(parents=True, exist_ok=True)

            # Build export set using cached catalog
            catalog = self._ensure_catalog()
            album = catalog["by_album"].get(album_name)
            files_to_export: List[Tuple[Path, str]] = []
            exported_photos = set()
            metadata_map: Dict[str, Tuple[Path, str]] = dict(album["supplemental_map"]) if album else {}
            album_path = f"Takeout/Google Photos/{album_name}/"

            if not album:
                stats["skipped"] += 1
                continue

            # album metadata.json
            if album.get("info_file"):
                files_to_export.append(album["info_file"])  # type: ignore[index]

            # direct media in album
            for zip_path, file_name in album["direct_media"]:
                photo_name = Path(file_name).name
                files_to_export.append((zip_path, file_name))
                exported_photos.add(photo_name)
                if photo_name in metadata_map:
                    files_to_export.append(metadata_map[photo_name])

            # referenced media resolved via cached index
            resolved = self.resolve_album_photos(album_name)
            for zip_path, file_name in resolved["photos"]:
                photo_name = Path(file_name).name
                if photo_name not in exported_photos:
                    files_to_export.append((zip_path, file_name))
                    exported_photos.add(photo_name)
                    if photo_name in metadata_map:
                        files_to_export.append(metadata_map[photo_name])

            # Prepare manifest entries (media files only)
            manifest_entries: List[Dict[str, Any]] = []

            # Export files
            for file_idx, (zip_path, file_name) in enumerate(files_to_export, 1):
                if file_progress_callback:
                    file_progress_callback(file_idx, len(files_to_export), album_name)

                try:
                    # Determine output path
                    if file_name.startswith(album_path):
                        # File is directly in album folder - preserve structure
                        relative_path = file_name[len(album_path) :]
                        if not relative_path:  # Skip if it's just the directory itself
                            continue
                        output_file = album_dir / relative_path
                    else:
                        # File is referenced from elsewhere - put directly in album folder
                        # This includes both photos from other locations and their metadata
                        output_file = album_dir / Path(file_name).name

                    # Skip if file already exists
                    if output_file.exists():
                        album_stats["skipped"] += 1
                        stats["skipped"] += 1
                        continue

                    # Create subdirectories if needed
                    output_file.parent.mkdir(parents=True, exist_ok=True)

                    # If this is a media file, collect metadata for manifest
                    ext = Path(file_name).suffix.lower()
                    is_media = ext in {
                        ".jpg",
                        ".jpeg",
                        ".png",
                        ".gif",
                        ".bmp",
                        ".webp",
                        ".heic",
                        ".mp4",
                        ".mov",
                        ".avi",
                        ".wmv",
                        ".m4v",
                        ".mpg",
                        ".mpeg",
                    }
                    if is_media:
                        rel_for_manifest = relative_path if file_name.startswith(album_path) else Path(file_name).name
                        file_entry: Dict[str, Any] = {
                            "relative_path": rel_for_manifest,
                            "source_zip": zip_path.name,
                            "archive_path": file_name,
                        }
                        # Album supplemental metadata (if present)
                        photo_name = Path(file_name).name
                        if photo_name in metadata_map:
                            m_zip, m_path = metadata_map[photo_name]
                            try:
                                with zipfile.ZipFile(m_zip, "r") as zf_meta:
                                    with zf_meta.open(m_path) as mf:
                                        file_entry["albumSupplemental"] = json.load(mf)
                            except Exception:
                                pass
                        # Original metadata (sibling JSON)
                        try:
                            with zipfile.ZipFile(zip_path, "r") as zf_src:
                                jpath = f"{file_name}.json"
                                if jpath in zf_src.namelist():
                                    with zf_src.open(jpath) as jf:
                                        file_entry["original"] = json.load(jf)
                        except Exception:
                            pass
                        manifest_entries.append(file_entry)

                    # Extract file
                    with zipfile.ZipFile(zip_path, "r") as zf:
                        with zf.open(file_name) as source:
                            with open(output_file, "wb") as target:
                                data = source.read()
                                target.write(data)
                                file_size = len(data)
                                album_stats["size"] += file_size
                                stats["total_size"] += file_size

                    album_stats["files"] += 1
                    stats["files_exported"] += 1

                except Exception:
                    album_stats["errors"] += 1
                    stats["errors"] += 1

            # Write manifest.json into album directory
            try:
                manifest = {
                    "album": album_name,
                    "entries": manifest_entries,
                }
                with open(album_dir / "manifest.json", "w") as mf:
                    json.dump(manifest, mf, indent=2)
            except Exception:
                # Non-fatal
                pass

            stats["albums_exported"] += 1
            stats["album_details"][album_name] = album_stats

        return stats

    # -----------------------
    # Upload functionality
    # -----------------------

    def upload_albums(
        self,
        album_names: List[str],
        target: Optional[UploadTarget] = None,
        include_metadata: bool = True,
        progress_callback=None,
        file_progress_callback=None,
        include_thumbnails: bool = False,
        thumbnails_only: bool = False,
    ) -> Dict[str, Any]:
        """Upload one or more albums to a storage provider.

        Args:
            album_names: Album names to upload
            target: Upload destination (provider/container/prefix)
            include_metadata: If True, also upload metadata JSON files
            progress_callback: Callback for album progress
            file_progress_callback: Callback for per-file progress
        Returns:
            Statistics dictionary
        """
        config = ConfigManager()
        provider, base_prefix = build_provider(config, target)

        stats = {
            "albums_uploaded": 0,
            "files_uploaded": 0,
            "errors": 0,
            "skipped": 0,
            "album_details": {},
            "error_details": [],  # sample of errors across all albums
        }

        image_exts = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".heic"}
        video_exts = {".mp4", ".mov", ".avi", ".wmv", ".m4v", ".mpg", ".mpeg"}

        for album_idx, album_name in enumerate(album_names, 1):
            if progress_callback:
                progress_callback(album_idx, len(album_names), album_name)

            album_stats = {
                "files": 0,
                "errors": 0,
                "skipped": 0,
                "error_details": [],
            }

            album_path = f"Takeout/Google Photos/{album_name}/"
            files_to_upload: List[Tuple[Path, str]] = []
            exported_photos = set()
            metadata_map: Dict[str, Tuple[Path, str]] = {}

            # Build upload set using cached catalog
            catalog = self._ensure_catalog()
            album = catalog["by_album"].get(album_name)
            files_to_upload: List[Tuple[Path, str]] = []
            exported_photos = set()
            metadata_map = dict(album["supplemental_map"]) if album else {}

            if not album:
                album_stats["skipped"] += 1
                stats["skipped"] += 1
                continue

            # album metadata.json (if include_metadata)
            if include_metadata and album.get("info_file"):
                files_to_upload.append(album["info_file"])  # type: ignore[index]

            # direct media in album
            for zip_path, file_name in album["direct_media"]:
                files_to_upload.append((zip_path, file_name))
                photo_name = Path(file_name).name
                exported_photos.add(photo_name)
                if include_metadata and photo_name in metadata_map:
                    files_to_upload.append(metadata_map[photo_name])

            # referenced media resolved via cached index
            resolved = self.resolve_album_photos(album_name)
            for zip_path, file_name in resolved["photos"]:
                photo_name = Path(file_name).name
                if photo_name not in exported_photos:
                    files_to_upload.append((zip_path, file_name))
                    exported_photos.add(photo_name)
                    if include_metadata and photo_name in metadata_map:
                        files_to_upload.append(metadata_map[photo_name])

            # Upload
            manifest_entries: List[Dict[str, Any]] = []
            for file_idx, (zip_path, file_name) in enumerate(files_to_upload, 1):
                if file_progress_callback:
                    file_progress_callback(file_idx, len(files_to_upload), album_name)
                try:
                    # Determine destination under prefix/album_name
                    dest_relative: str
                    if file_name.startswith(album_path):
                        rel = file_name[len(album_path) :]
                        if not rel:
                            continue
                        # Flatten to album_name/<image_name or metadata>
                        dest_relative = f"{album_name}/{Path(rel).name}"
                    else:
                        dest_relative = f"{album_name}/{Path(file_name).name}"

                    destination_path = sanitize_blob_path(base_prefix + dest_relative)
                    content_type = detect_content_type(file_name)

                    # Upload original and/or thumbnail
                    with zipfile.ZipFile(zip_path, "r") as zf:
                        with zf.open(file_name) as source:
                            data = source.read()

                    ext = Path(file_name).suffix.lower()
                    is_image = ext in {
                        ".jpg",
                        ".jpeg",
                        ".png",
                        ".gif",
                        ".bmp",
                        ".webp",
                        ".heic",
                    }

                    # Upload original unless thumbnails_only is set
                    if not thumbnails_only:
                        provider.upload_bytes(data, destination_path, content_type=content_type)
                        album_stats["files"] += 1
                        stats["files_uploaded"] += 1

                    # Upload thumbnail if requested and if it's an image we can handle
                    if (include_thumbnails or thumbnails_only) and is_image:
                        try:
                            thumb_bytes, thumb_ct = generate_thumbnail(data, original_ext=ext, max_size=(512, 512))
                            if thumb_bytes and thumb_ct:
                                thumb_dest_relative = f"{album_name}/thumb-" + Path(dest_relative).name
                                thumb_destination_path = sanitize_blob_path(base_prefix + thumb_dest_relative)
                                provider.upload_bytes(thumb_bytes, thumb_destination_path, content_type=thumb_ct)
                                album_stats["files"] += 1
                                stats["files_uploaded"] += 1
                        except Exception:
                            # Ignore thumbnail errors; originals may still upload
                            pass

                    # If media, collect manifest entry with metadata
                    ext = Path(file_name).suffix.lower()
                    if ext in image_exts or ext in video_exts:
                        entry: Dict[str, Any] = {
                            "relative_path": dest_relative.split(f"{album_name}/", 1)[-1],
                            "destination": destination_path,
                            "source_zip": zip_path.name,
                            "archive_path": file_name,
                        }
                        # Album supplemental metadata (if present)
                        photo_name = Path(file_name).name
                        if photo_name in metadata_map:
                            m_zip, m_path = metadata_map[photo_name]
                            try:
                                with zipfile.ZipFile(m_zip, "r") as zf_meta:
                                    with zf_meta.open(m_path) as mf:
                                        entry["albumSupplemental"] = json.load(mf)
                            except Exception:
                                pass
                        # Original metadata (sibling JSON)
                        try:
                            with zipfile.ZipFile(zip_path, "r") as zf_src:
                                jpath = f"{file_name}.json"
                                if jpath in zf_src.namelist():
                                    with zf_src.open(jpath) as jf:
                                        entry["original"] = json.load(jf)
                        except Exception:
                            pass
                        manifest_entries.append(entry)
                except Exception as e:
                    album_stats["errors"] += 1
                    stats["errors"] += 1
                    # Capture a limited sample of errors for display
                    detail = {
                        "album": album_name,
                        "file": file_name,
                        "dest": destination_path,
                        "error": f"{type(e).__name__}: {e}",
                    }
                    if len(album_stats["error_details"]) < 20:
                        album_stats["error_details"].append(detail)
                    if len(stats["error_details"]) < 50:
                        stats["error_details"].append(detail)

            # Upload manifest.json for this album
            try:
                manifest = {
                    "album": album_name,
                    "entries": manifest_entries,
                }
                manifest_bytes = json.dumps(manifest, indent=2).encode("utf-8")
                manifest_path = sanitize_blob_path(base_prefix + f"{album_name}/manifest.json")
                provider.upload_bytes(
                    manifest_bytes,
                    manifest_path,
                    content_type="application/json",
                )
            except Exception:
                # Non-fatal
                pass

            stats["albums_uploaded"] += 1
            stats["album_details"][album_name] = album_stats

        return stats

    def upload_by_pattern(
        self,
        pattern: str,
        target: Optional[UploadTarget] = None,
        include_metadata: bool = False,
        progress_callback=None,
        file_progress_callback=None,
        include_thumbnails: bool = False,
        thumbnails_only: bool = False,
    ) -> Dict[str, Any]:
        """Upload files matching a regex pattern across all zips.

        Note: include_metadata will only include JSON files that also match the pattern.
        """
        config = ConfigManager()
        provider, base_prefix = build_provider(config, target)

        regex = re.compile(pattern, re.IGNORECASE)
        stats = {
            "files_uploaded": 0,
            "errors": 0,
            "skipped": 0,
            "total_matched": 0,
            "error_details": [],
        }

        all_matches: List[Tuple[Path, str]] = []
        catalog = self._ensure_catalog()
        by_zip: Dict[Path, List[str]] = catalog["by_zip"]
        total = len(self.zip_files)
        for idx, zip_path in enumerate(self.zip_files, 1):
            names = by_zip.get(zip_path, [])
            for file_name in names:
                if regex.search(file_name):
                    if not include_metadata and file_name.lower().endswith(".json"):
                        continue
                    all_matches.append((zip_path, file_name))
            if progress_callback:
                progress_callback(idx, total)

        stats["total_matched"] = len(all_matches)

        for idx, (zip_path, file_name) in enumerate(all_matches, 1):
            if file_progress_callback:
                file_progress_callback(idx, len(all_matches), file_name)
            try:
                # Keep pattern uploads preserving relative structure but sanitized
                destination_path = sanitize_blob_path(base_prefix + file_name)
                content_type = detect_content_type(file_name)
                with zipfile.ZipFile(zip_path, "r") as zf:
                    with zf.open(file_name) as source:
                        data = source.read()

                ext = Path(file_name).suffix.lower()
                is_image = ext in {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".heic"}

                if not thumbnails_only:
                    provider.upload_bytes(data, destination_path, content_type=content_type)
                    stats["files_uploaded"] += 1

                if (include_thumbnails or thumbnails_only) and is_image:
                    try:
                        thumb_bytes, thumb_ct = generate_thumbnail(data, original_ext=ext, max_size=(512, 512))
                        if thumb_bytes and thumb_ct:
                            from pathlib import Path as _P

                            thumb_archive_path = str(_P(file_name).with_name("thumb-" + _P(file_name).name))
                            thumb_destination_path = sanitize_blob_path(base_prefix + thumb_archive_path)
                            provider.upload_bytes(thumb_bytes, thumb_destination_path, content_type=thumb_ct)
                            stats["files_uploaded"] += 1
                    except Exception:
                        pass
            except Exception as e:
                stats["errors"] += 1
                if len(stats["error_details"]) < 50:
                    stats["error_details"].append(
                        {"file": file_name, "dest": destination_path, "error": f"{type(e).__name__}: {e}"}
                    )

        return stats

    def upload_from_results(
        self,
        results: Dict[str, List[str]],
        target: Optional[UploadTarget] = None,
        include_metadata: bool = False,
        file_progress_callback=None,
        include_thumbnails: bool = False,
        thumbnails_only: bool = False,
    ) -> Dict[str, Any]:
        """Upload files from a precomputed results mapping of zip_name -> file paths."""
        config = ConfigManager()
        provider, base_prefix = build_provider(config, target)

        name_to_path = {p.name: p for p in self.zip_files}

        pending: List[Tuple[Path, str]] = []
        for zip_name, files in results.items():
            zip_path = name_to_path.get(zip_name)
            if not zip_path:
                continue
            for file_name in files:
                if not include_metadata and file_name.lower().endswith(".json"):
                    continue
                pending.append((zip_path, file_name))

        stats = {
            "files_uploaded": 0,
            "errors": 0,
            "skipped": 0,
            "total": len(pending),
            "error_details": [],
        }

        for idx, (zip_path, file_name) in enumerate(pending, 1):
            if file_progress_callback:
                file_progress_callback(idx, len(pending), file_name)
            try:
                destination_path = sanitize_blob_path(base_prefix + file_name)
                content_type = detect_content_type(file_name)
                with zipfile.ZipFile(zip_path, "r") as zf:
                    with zf.open(file_name) as source:
                        data = source.read()

                ext = Path(file_name).suffix.lower()
                is_image = ext in {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".heic"}

                if not thumbnails_only:
                    provider.upload_bytes(data, destination_path, content_type=content_type)
                    stats["files_uploaded"] += 1

                if (include_thumbnails or thumbnails_only) and is_image:
                    try:
                        thumb_bytes, thumb_ct = generate_thumbnail(data, original_ext=ext, max_size=(512, 512))
                        if thumb_bytes and thumb_ct:
                            from pathlib import Path as _P

                            thumb_archive_path = str(_P(file_name).with_name("thumb-" + _P(file_name).name))
                            thumb_destination_path = sanitize_blob_path(base_prefix + thumb_archive_path)
                            provider.upload_bytes(thumb_bytes, thumb_destination_path, content_type=thumb_ct)
                            stats["files_uploaded"] += 1
                    except Exception:
                        pass
            except Exception as e:
                stats["errors"] += 1
                if len(stats["error_details"]) < 50:
                    stats["error_details"].append(
                        {"file": file_name, "dest": destination_path, "error": f"{type(e).__name__}: {e}"}
                    )

        return stats
        return stats
