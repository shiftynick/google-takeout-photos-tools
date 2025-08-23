#!/usr/bin/env python3
"""
Google Photos Takeout Explorer
A CLI tool to explore Google Photos takeout zip files without extracting them
all. Supports both command-line and interactive modes.
"""

import argparse
import sys

from core.config import ConfigManager
from core.explorer import GooglePhotosExplorer
from core.output import OutputFormatter
from core.upload import UploadTarget
from interactive.shell import run_interactive


def main():
    parser = argparse.ArgumentParser(
        description=("Explore Google Photos Takeout zips " "without extracting them all"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=r"""
Examples:
  %(prog)s /path/to/zips --list
  %(prog)s /path/to/zips --explore 1
  %(prog)s /path/to/zips --search "IMG_.*\.jpg"
  %(prog)s /path/to/zips --metadata ".*2023.*" --output metadata_2023.json
  %(prog)s /path/to/zips --date-range
  %(prog)s /path/to/zips --folders
  %(prog)s /path/to/zips --extract 1 "Takeout/Google Photos/2023/IMG_1234.jpg"
  %(prog)s /path/to/zips --export-albums "Photos from 2023,Bali"
  %(prog)s /path/to/zips --interactive  # Enter interactive mode
        """,
    )

    parser.add_argument(
        "zip_directory",
        help="Directory containing Google Photos takeout zip files",
    )
    parser.add_argument("--list", action="store_true", help="List all zip files")
    parser.add_argument(
        "--explore",
        type=int,
        metavar="N",
        help="Explore contents of zip file N",
    )
    parser.add_argument(
        "--search",
        metavar="PATTERN",
        help="Search for files matching regex pattern",
    )
    parser.add_argument(
        "--metadata",
        metavar="PATTERN",
        help="Extract metadata for files matching pattern",
    )
    parser.add_argument("--output", metavar="FILE", help="Output file for metadata extraction")
    parser.add_argument(
        "--date-range",
        action="store_true",
        help="Analyze date range of all photos",
    )
    parser.add_argument(
        "--folders",
        action="store_true",
        help="List all unique folders across all zips",
    )
    parser.add_argument(
        "--extract",
        nargs=2,
        metavar=("ZIP_INDEX", "FILE_PATH"),
        help="Extract specific file from zip",
    )
    parser.add_argument(
        "--extract-to",
        metavar="DIR",
        default=".",
        help="Directory to extract files to (default: current directory)",
    )
    parser.add_argument(
        "--export-albums",
        metavar="ALBUMS",
        help=("Export albums (comma-separated) to directory " "specified by --export-to"),
    )
    parser.add_argument(
        "--export-to",
        metavar="DIR",
        default="./exported_albums",
        help="Directory to export albums to (default: ./exported_albums)",
    )
    parser.add_argument(
        "--interactive",
        "-i",
        action="store_true",
        help="Enter interactive mode for exploring photos",
    )

    # Azure configuration options
    parser.add_argument(
        "--azure-set-connection",
        metavar="CONNECTION_STRING",
        help="Set Azure Storage connection string",
    )
    parser.add_argument(
        "--azure-set-container",
        metavar="CONTAINER",
        help="Set default Azure Storage container",
    )
    parser.add_argument(
        "--azure-set-prefix",
        metavar="PREFIX",
        help="Set default Azure upload prefix (e.g., backups/2025-01-01)",
    )

    # Upload options
    parser.add_argument(
        "--upload-albums",
        metavar="ALBUMS",
        help=("Upload albums (comma-separated) to storage " "(default provider: azure)"),
    )
    parser.add_argument(
        "--upload-pattern",
        metavar="PATTERN",
        help="Upload files matching regex pattern to storage",
    )
    parser.add_argument(
        "--upload-container",
        metavar="CONTAINER",
        help="Override container for this upload",
    )
    parser.add_argument(
        "--upload-prefix",
        metavar="PREFIX",
        help=("Prefix within storage to upload into " "(overrides default prefix)"),
    )
    parser.add_argument(
        "--upload-include-metadata",
        action="store_true",
        help="Include metadata files (.json) in upload",
    )
    parser.add_argument(
        "--provider",
        default="azure",
        metavar="PROVIDER",
        help="Storage provider to use (currently only azure is supported)",
    )

    args = parser.parse_args()

    try:
        # Check if interactive mode requested
        if args.interactive:
            run_interactive(args.zip_directory)
            return

        # Create explorer and formatter for command-line mode
        explorer = GooglePhotosExplorer(args.zip_directory)
        formatter = OutputFormatter()
        config = ConfigManager()

        # Track if any action was performed
        action_performed = False

        # Configuration actions
        if args.azure_set_connection:
            config.set_azure_connection_string(args.azure_set_connection)
            print("Azure connection string saved.")
            action_performed = True
        if args.azure_set_container:
            config.set_azure_container(args.azure_set_container)
            print("Azure container saved.")
            action_performed = True
        if args.azure_set_prefix is not None:
            config.set_azure_default_prefix(args.azure_set_prefix)
            print("Azure default prefix saved.")
            action_performed = True

        # Execute requested operations
        if args.list:
            zip_list = explorer.list_zips()
            formatter.print_zip_list(zip_list)
            action_performed = True

        if args.explore:
            data = explorer.explore_zip(args.explore)
            formatter.print_zip_exploration(data)
            action_performed = True

        if args.search:

            def progress_callback(i, t):
                formatter.print_progress(i, t, "Searching")

            results = explorer.search_files(args.search, progress_callback)
            print()  # New line after progress
            formatter.print_search_results(results, args.search)
            action_performed = True

        if args.metadata:

            def progress_callback(i, t):
                formatter.print_progress(i, t, "Extracting")

            metadata = explorer.extract_metadata(args.metadata, progress_callback)
            print()  # New line after progress
            formatter.print_metadata_extraction(metadata, args.metadata)

            if args.output and metadata:
                formatter.save_metadata(metadata, args.output)
            action_performed = True

        if args.date_range:

            def progress_callback(i, t):
                formatter.print_progress(i, t, "Analyzing")

            data = explorer.get_date_range(progress_callback)
            print()  # New line after progress
            formatter.print_date_range(data)
            action_performed = True

        if args.folders:

            def progress_callback(i, t):
                formatter.print_progress(i, t, "Scanning")

            print("Scanning all zip files for folders and counting files...")
            data = explorer.list_folders(progress_callback)
            formatter.print_folders(data)
            action_performed = True

        if args.extract:
            zip_index = int(args.extract[0])
            file_path = args.extract[1]
            success = explorer.extract_file(zip_index, file_path, args.extract_to)
            formatter.print_extraction_result(success, file_path, args.extract_to)
            action_performed = True

        if args.export_albums:
            # Parse album names
            album_names = [a.strip() for a in args.export_albums.split(",")]

            print(f"Preparing to export {len(album_names)} album(s) to: {args.export_to}")

            def album_progress(current, total, album_name):
                print(f"\n[{current}/{total}] Exporting album: {album_name}")

            def file_progress(current, total, album_name):
                percent = (current / total * 100) if total > 0 else 0
                bar_length = 40
                filled = int(bar_length * current / total) if total > 0 else 0
                bar = "█" * filled + "░" * (bar_length - filled)
                print(f"\r  {bar} {percent:.1f}% ({current}/{total} files)", end="", flush=True)

            stats = explorer.export_albums(
                album_names, args.export_to, progress_callback=album_progress, file_progress_callback=file_progress
            )

            formatter.print_export_stats(stats)
            action_performed = True

        # Upload operations
        if args.upload_albums:
            album_names = [a.strip() for a in args.upload_albums.split(",") if a.strip()]
            print(f"Preparing to upload {len(album_names)} album(s) to provider: " f"{args.provider}")

            def album_progress(current, total, album_name):
                print(f"\n[{current}/{total}] Uploading album: {album_name}")

            def file_progress(current, total, album_name):
                percent = (current / total * 100) if total > 0 else 0
                bar_length = 40
                filled = int(bar_length * current / total) if total > 0 else 0
                bar = "█" * filled + "░" * (bar_length - filled)
                print(
                    f"\r  {bar} {percent:.1f}% ({current}/{total} files)",
                    end="",
                    flush=True,
                )

            target = UploadTarget(
                provider=args.provider,
                container=args.upload_container,
                prefix=(args.upload_prefix or ""),
            )
            stats = explorer.upload_albums(
                album_names,
                target=target,
                include_metadata=args.upload_include_metadata,
                progress_callback=album_progress,
                file_progress_callback=file_progress,
            )
            formatter.print_upload_stats(stats, scope_label="Upload Complete")
            action_performed = True

        if args.upload_pattern:
            print("Preparing to upload files matching pattern to provider: " f"{args.provider}")

            def progress_callback(i, t):
                formatter.print_progress(i, t, "Scanning")

            def file_progress(current, total, item_name):
                percent = (current / total * 100) if total > 0 else 0
                bar_length = 40
                filled = int(bar_length * current / total) if total > 0 else 0
                bar = "█" * filled + "░" * (bar_length - filled)
                print(f"\r  {bar} {percent:.1f}% ({current}/{total} files)", end="", flush=True)

            target = UploadTarget(
                provider=args.provider,
                container=args.upload_container,
                prefix=(args.upload_prefix or ""),
            )
            stats = explorer.upload_by_pattern(
                args.upload_pattern,
                target=target,
                include_metadata=args.upload_include_metadata,
                progress_callback=progress_callback,
                file_progress_callback=lambda c, t, _: file_progress(c, t, ""),
            )
            print()
            formatter.print_upload_stats(stats, scope_label="Upload Complete")
            action_performed = True

        # If no specific action requested, show help
        if not action_performed:
            parser.print_help()

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
