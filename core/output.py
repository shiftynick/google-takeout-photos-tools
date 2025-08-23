"""Output formatting for Google Photos Explorer."""

import json
from typing import Any, Dict, List, Optional, Tuple


class OutputFormatter:
    """Handles formatting and display of explorer results."""

    @staticmethod
    def print_zip_list(zip_list: List[Dict[str, Any]]) -> None:
        """Print formatted list of zip files."""
        print(f"\nFound {len(zip_list)} zip files:")
        print("-" * 50)
        for item in zip_list:
            print(f"{item['index']:3d}. {item['name']} ({item['size_mb']:.1f} MB)")

    @staticmethod
    def print_zip_exploration(data: Optional[Dict[str, Any]]) -> None:
        """Print formatted zip exploration results."""
        if not data:
            print("Invalid zip index.")
            return

        print(f"\nExploring: {data['zip_name']}")
        print("-" * 50)
        print(f"Total files: {data['total_files']}")
        print(f"  Images: {data['counts']['images']}")
        print(f"  Videos: {data['counts']['videos']}")
        print(f"  JSON metadata: {data['counts']['json']}")
        print(f"  Other: {data['counts']['other']}")

        if data["sample_files"]:
            print("\nSample files (first 10):")
            for file_name in data["sample_files"]:
                print(f"  {file_name}")

    @staticmethod
    def print_search_results(results: Dict[str, List[str]], pattern: str) -> None:
        """Print formatted search results."""
        print(f"\nSearching for pattern: {pattern}")
        print("-" * 50)

        if not results:
            print("No matches found.")
            return

        total_matches = sum(len(matches) for matches in results.values())

        for zip_name, matches in results.items():
            print(f"\n{zip_name}: {len(matches)} matches")
            for match in matches[:5]:
                print(f"  {match}")
            if len(matches) > 5:
                print(f"  ... and {len(matches) - 5} more")

        print(f"\nTotal matches: {total_matches}")

    @staticmethod
    def print_metadata_extraction(metadata: List[Dict], pattern: str) -> None:
        """Print metadata extraction results."""
        print(f"\nExtracting metadata for pattern: {pattern}")
        print("-" * 50)
        print(f"Found {len(metadata)} metadata entries")

        if metadata and len(metadata) > 0:
            print("\nSample metadata (first entry):")
            print(json.dumps(metadata[0], indent=2))

    @staticmethod
    def save_metadata(metadata: List[Dict], output_file: str) -> None:
        """Save metadata to JSON file."""
        with open(output_file, "w") as f:
            json.dump(metadata, f, indent=2)
        print(f"Metadata saved to {output_file}")

    @staticmethod
    def print_date_range(data: Dict[str, Any]) -> None:
        """Print date range analysis results."""
        print("\nAnalyzing date range of photos...")
        print("-" * 50)

        if data["total_photos"] > 0:
            print(f"Total photos with dates: {data['total_photos']}")
            print(f"Earliest photo: {data['earliest_date'].strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"Latest photo: {data['latest_date'].strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"Errors processing: {data['errors']}")
        else:
            print("No date information found")
            print(f"Errors processing: {data['errors']}")

    @staticmethod
    def print_folders(data: Dict[str, Any], show_breakdown: bool = False) -> None:
        """Print folder listing with counts."""
        print(f"\n\nFound {data['total_folders']} unique folders across " f"{data['total_files']:,} files")
        print("-" * 50)

        album_folders = data["album_folders"]

        print("\nGoogle Photos Albums (sorted alphabetically):")

        if show_breakdown and any("images_direct" in stats for stats in album_folders.values()):
            # Show detailed breakdown
            print("-" * 100)
            print(f"{'Album Name':<40} {'Direct':>8} {'Ref':>8} {'Total':>8} | {'Videos':>8} {'Total':>10}")
            print(f"{'':<40} {'Images':>8} {'Images':>8} {'Images':>8} |")
            print("-" * 100)

            for album_name in sorted(album_folders.keys()):
                stats = album_folders[album_name]
                total_media = stats["images"] + stats["videos"]
                if total_media > 0 or stats.get("images_referenced", 0) > 0:
                    print(
                        f"{album_name[:39]:<40} {stats.get('images_direct', 0):>8} "
                        f"{stats.get('images_referenced', 0):>8} {stats['images']:>8} | "
                        f"{stats['videos']:>8} {total_media:>10}"
                    )
        else:
            # Simple view
            print("-" * 80)
            print(f"{'Album Name':<50} {'Images':>8} {'Videos':>8} {'Total':>8}")
            print("-" * 80)

            for album_name in sorted(album_folders.keys()):
                stats = album_folders[album_name]
                total = stats["images"] + stats["videos"]
                if total > 0:
                    print(f"{album_name[:49]:<50} {stats['images']:>8} " f"{stats['videos']:>8} {total:>8}")

        # Summary statistics
        print("-" * 80)
        total_images = sum(s["images"] for s in album_folders.values())
        total_videos = sum(s["videos"] for s in album_folders.values())
        print(f"{'TOTAL':<50} {total_images:>8} {total_videos:>8} " f"{total_images + total_videos:>8}")
        print(f"\nTotal albums: {len(album_folders)}")
        print(f"Total metadata files: {sum(s['json'] for s in album_folders.values()):,}")

    @staticmethod
    def print_extraction_result(success: bool, file_path: str, output_dir: str) -> None:
        """Print file extraction result."""
        if success:
            print(f"Extracted: {file_path} to {output_dir}")
        else:
            print(f"Failed to extract: {file_path}")

    @staticmethod
    def print_progress(current: int, total: int, prefix: str = "Processing") -> None:
        """Print progress indicator."""
        print(f"\r{prefix} zip {current}/{total}...", end="", flush=True)

    @staticmethod
    def print_index_progress(current: int, total: int, prefix: str = "Indexing") -> None:
        """Print a progress bar for index/catalog building."""
        percent = (current / total * 100) if total > 0 else 0
        bar_length = 40
        filled = int(bar_length * current / total) if total > 0 else 0
        bar = "█" * filled + "░" * (bar_length - filled)
        print(f"\r{prefix} {bar} {percent:.1f}% ({current}/{total} zips)", end="", flush=True)

    @staticmethod
    def print_export_progress(current: int, total: int, item_name: str, prefix: str = "Exporting") -> None:
        """Print export progress with item name."""
        print(
            f"\r{prefix} ({current}/{total}): {item_name[:50]:<50}",
            end="",
            flush=True,
        )

    @staticmethod
    def print_export_stats(stats: Dict[str, Any]) -> None:
        """Print export statistics."""
        print("\n\nExport Complete!")
        print("-" * 50)
        print(f"Albums exported: {stats['albums_exported']}")
        print(f"Files exported: {stats['files_exported']}")
        print(f"Files skipped (already exist): {stats['skipped']}")
        print(f"Errors: {stats['errors']}")
        print(f"Total size: {stats['total_size'] / (1024**2):.1f} MB")

        if stats["album_details"]:
            print("\nPer-album statistics:")
            for album_name, details in stats["album_details"].items():
                print(f"  {album_name}:")
                print(f"    Files: {details['files']}, Skipped: {details['skipped']}, " f"Errors: {details['errors']}")
                print(f"    Size: {details['size'] / (1024**2):.1f} MB")

    @staticmethod
    def print_upload_stats(stats: Dict[str, Any], scope_label: str = "Upload Complete") -> None:
        """Print upload statistics for album or pattern uploads."""
        print(f"\n\n{scope_label}!")
        print("-" * 50)
        # Support both album and general upload stats keys
        if "albums_uploaded" in stats:
            print(f"Albums uploaded: {stats['albums_uploaded']}")
        if "total" in stats:
            print(f"Total files considered: {stats['total']}")
        if "total_matched" in stats:
            print(f"Total matched: {stats['total_matched']}")
        print(f"Files uploaded: {stats.get('files_uploaded', 0)}")
        print(f"Files skipped: {stats.get('skipped', 0)}")
        print(f"Errors: {stats.get('errors', 0)}")
        # Show sample errors if present
        if stats.get("error_details"):
            print("\nSample errors:")
            for entry in stats["error_details"][:10]:
                file_desc = entry.get("file", "?")
                album_desc = entry.get("album")
                prefix = f"[{album_desc}] " if album_desc else ""
                print(f"  - {prefix}{file_desc}: {entry.get('error')}")
        if stats.get("album_details"):
            print("\nPer-album statistics:")
            for album_name, details in stats["album_details"].items():
                print(f"  {album_name}:")
                print(
                    f"    Files: {details.get('files', 0)}, Skipped: {details.get('skipped', 0)}, Errors: {details.get('errors', 0)}"  # noqa: E501
                )
                # Per-album sample errors
                if details.get("error_details"):
                    for entry in details["error_details"][:5]:
                        print(f"      - {entry.get('file')}: {entry.get('error')}")

    @staticmethod
    def print_album_files(
        album_name: str, media_files: List[Tuple[str, str]], metadata_files: Optional[List[Tuple[str, str]]] = None
    ) -> None:
        """Print files for a specific album context.

        media_files contains tuples of (zip_name, file_path).
        metadata_files, if provided, contains tuples of (zip_name, file_path).
        """
        print(f"\nFiles in album: {album_name}")
        print("-" * 80)

        total_media = len(media_files)
        print(f"Media files: {total_media}")

        # Show up to first 20 media entries grouped by zip
        if total_media == 0:
            print("  (no media files found)")
        else:
            max_show = 20
            for idx, (zip_name, path) in enumerate(media_files[:max_show], 1):
                print(f"  {idx:3d}. [{zip_name}] {path}")
            if total_media > max_show:
                print(f"  ... and {total_media - max_show} more")

        # Optionally show metadata files
        if metadata_files is not None:
            print("\nMetadata files in album folder:")
            count_meta = len(metadata_files)
            print(f"  Total: {count_meta}")
            if count_meta == 0:
                print("  (none)")
            else:
                max_show_meta = 10
                for idx, (zip_name, path) in enumerate(metadata_files[:max_show_meta], 1):
                    print(f"  {idx:3d}. [{zip_name}] {path}")
                if count_meta > max_show_meta:
                    print(f"  ... and {count_meta - max_show_meta} more")
