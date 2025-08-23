"""Interactive shell for Google Photos Explorer."""

import cmd
import json
import readline
import sys
from pathlib import Path
from typing import List

from core.config import ConfigManager
from core.explorer import GooglePhotosExplorer
from core.output import OutputFormatter
from core.upload import UploadTarget


class GooglePhotosInteractiveShell(cmd.Cmd):
    """Interactive command shell for exploring Google Photos takeout files."""

    intro = """
    ╔══════════════════════════════════════════════════════════════════╗
    ║         Google Photos Takeout Explorer - Interactive Mode       ║
    ╠══════════════════════════════════════════════════════════════════╣
    ║  Type 'help' for commands or 'help <command>' for details       ║
    ║  Tab completion available for commands and arguments            ║
    ║  Type 'quit' or 'exit' to leave                                ║
    ╚══════════════════════════════════════════════════════════════════╝
    """

    prompt = "gphoto> "

    def __init__(self, zip_directory: str):
        super().__init__()
        # Eagerly build catalog to speed up subsequent commands (with progress bar)
        self.explorer = GooglePhotosExplorer(
            zip_directory,
            preload_catalog=True,
            catalog_progress_callback=lambda i, t: OutputFormatter.print_index_progress(i, t, "Indexing"),
        )
        print()  # newline after progress bar
        self.formatter = OutputFormatter()
        self.config = ConfigManager()
        self.current_zip = None
        self.last_search_results = None
        self.last_metadata = None
        self.current_album = None

        # Enable tab completion
        if "libedit" in readline.__doc__:
            readline.parse_and_bind("bind ^I rl_complete")
        else:
            readline.parse_and_bind("tab: complete")

        # Cache for performance (album list still cached for quick UI lookups)
        self._album_cache = None
        self._file_cache = {}

    @staticmethod
    def _clean_cli_value(val: str) -> str:
        """Strip surrounding quotes and whitespace from a CLI token."""
        return val.strip().strip('"').strip("'")

    def do_list(self, arg):
        """List all zip files.
        Usage: list"""
        zip_list = self.explorer.list_zips()
        self.formatter.print_zip_list(zip_list)

    def do_ls(self, arg):
        """List zip files at root, or files in current album.
        Usage: ls [-a]

        At root (no album selected), lists all zip files.
        Inside an album, lists media files (images/videos) in the current album.
        Use -a to include metadata files as well when inside an album.
        """
        # If we're inside an album, list files for that album
        if self.current_album:
            include_metadata = arg.strip() == "-a"
            self._list_files_in_current_album(include_metadata=include_metadata)
            return

        # Otherwise, list zip files (original behavior)
        self.do_list(arg)

    def do_explore(self, arg):
        """Explore contents of a specific zip file.
        Usage: explore <zip_number>
        Example: explore 1"""
        try:
            if not arg:
                print("Please specify a zip number. Use 'list' to see available zips.")
                return

            zip_index = int(arg)
            data = self.explorer.explore_zip(zip_index)

            if data:
                self.current_zip = zip_index
                self.formatter.print_zip_exploration(data)
            else:
                print(f"Invalid zip index. Please choose between 1 and {len(self.explorer.zip_files)}")
        except ValueError:
            print("Please provide a valid number.")

    def do_search(self, pattern):
        """Search for files matching a regex pattern across all zips.
        Usage: search <pattern>
        Example: search IMG_.*\\.jpg
        Example: search .*2023.*"""
        if not pattern:
            print("Please provide a search pattern.")
            return

        print(f"Searching for pattern: {pattern}")
        results = self.explorer.search_files(
            pattern, progress_callback=lambda i, t: self.formatter.print_progress(i, t, "Searching")
        )
        print()  # New line after progress

        self.last_search_results = results
        self.formatter.print_search_results(results, pattern)

    def do_folders(self, arg):
        """List all folders with file counts.
        Usage: folders"""
        print("Scanning all zip files for folders and counting files...")
        data = self.explorer.list_folders(
            progress_callback=lambda i, t: self.formatter.print_progress(i, t, "Scanning")
        )
        self._album_cache = data["album_folders"]
        self.formatter.print_folders(data)

    def do_albums(self, arg):
        """Alias for 'folders'.
        Usage: albums"""
        self.do_folders(arg)

    def do_metadata(self, args):
        """Extract metadata from JSON files.
        Usage: metadata <pattern> [output_file]
        Example: metadata IMG_.*\\.json
        Example: metadata .*2023.* output.json"""
        parts = args.split(maxsplit=1)
        if not parts:
            print("Please provide a pattern to search for.")
            return

        pattern = parts[0]
        output_file = parts[1] if len(parts) > 1 else None

        print(f"Extracting metadata for pattern: {pattern}")
        metadata = self.explorer.extract_metadata(
            pattern, progress_callback=lambda i, t: self.formatter.print_progress(i, t, "Extracting")
        )
        print()  # New line after progress

        self.last_metadata = metadata
        self.formatter.print_metadata_extraction(metadata, pattern)

        if output_file and metadata:
            self.formatter.save_metadata(metadata, output_file)

    def do_daterange(self, arg):
        """Analyze date range of all photos.
        Usage: daterange"""
        data = self.explorer.get_date_range(
            progress_callback=lambda i, t: self.formatter.print_progress(i, t, "Analyzing")
        )
        print()  # New line after progress
        self.formatter.print_date_range(data)

    def do_extract(self, args):
        """Extract a specific file from a zip.
        Usage: extract <zip_number> <file_path> [output_dir]
        Example: extract 1 "Takeout/Google Photos/2023/IMG_1234.jpg"
        Example: extract 1 "Takeout/Google Photos/2023/IMG_1234.jpg" ./extracted"""
        parts = args.split(maxsplit=2)
        if len(parts) < 2:
            print("Usage: extract <zip_number> <file_path> [output_dir]")
            return

        try:
            zip_index = int(parts[0])
            file_path = parts[1].strip('"')
            output_dir = parts[2] if len(parts) > 2 else "."

            success = self.explorer.extract_file(zip_index, file_path, output_dir)
            self.formatter.print_extraction_result(success, file_path, output_dir)
        except ValueError:
            print("Please provide a valid zip number.")

    def do_cd(self, album_name):
        """Change context to a specific album.
        Usage: cd <album_name>
        Example: cd "Photos from 2023"
        Use 'cd ..' to go back to root"""
        if album_name == "..":
            self.current_album = None
            print("Changed to root directory")
            return

        if not album_name:
            print("Please provide an album name. Use 'folders' to see available albums.")
            return

        # Remove quotes if present
        album_name = album_name.strip('"')

        # Load album cache if needed
        if not self._album_cache:
            print("Loading album information...")
            data = self.explorer.list_folders()
            self._album_cache = data["album_folders"]

        if album_name in self._album_cache:
            self.current_album = album_name
            stats = self._album_cache[album_name]
            print(f"Changed to album: {album_name}")
            print(f"  Images: {stats['images']}, Videos: {stats['videos']}")
            self.prompt = f"gphoto [{album_name}]> "
        else:
            print(f"Album '{album_name}' not found. Use 'folders' to see available albums.")

    def do_pwd(self, arg):
        """Show current album context.
        Usage: pwd"""
        if self.current_album:
            print(f"Current album: {self.current_album}")
        else:
            print("At root level (no album selected)")

    def _list_files_in_current_album(self, include_metadata: bool = False):
        """List files for the current album context."""
        if not self.current_album:
            print("At root level. Use 'ls' to list zip files or 'folders' to view albums.")
            return

        # Collect direct media files in the album folder
        album_name = self.current_album
        image_exts = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".heic"}
        video_exts = {".mp4", ".mov", ".avi", ".wmv", ".m4v", ".mpg", ".mpeg"}
        media_exts = image_exts.union(video_exts)

        # Direct contents in album folder
        direct = self.explorer.get_album_contents(album_name)
        direct_media = []
        direct_metadata = []
        for zip_name, file_path in direct:
            ext = Path(file_path).suffix.lower()
            if ext in media_exts:
                direct_media.append((zip_name, file_path))
            elif file_path.endswith(".json"):
                direct_metadata.append((zip_name, file_path))

        # Referenced photos resolved from metadata
        resolved = self.explorer.resolve_album_photos(album_name)
        referenced_media = []
        for zip_path, file_path in resolved["photos"]:
            referenced_media.append((zip_path.name, file_path))

        # Combine and deduplicate media
        seen = set()
        all_media = []
        for pair in direct_media + referenced_media:
            if pair not in seen:
                seen.add(pair)
                all_media.append(pair)

        # Optionally include metadata files present in the album folder
        metadata_files = direct_metadata if include_metadata else None

        self.formatter.print_album_files(album_name, all_media, metadata_files)

    def do_config(self, args):
        """Manage configuration.
        Usage:
          config azure show
          config azure set connection <CONNECTION_STRING>
          config azure set container <CONTAINER>
          config azure set prefix <PREFIX>
        """
        parts = args.split()
        if not parts or parts[0] not in {"azure"}:
            print("Usage: config azure [show|set ...]")
            return
        if parts[0] == "azure":
            if len(parts) == 2 and parts[1] == "show":
                print("Azure configuration:")
                print(f"  Connection string: {'set' if self.config.get_azure_connection_string() else 'not set'}")
                print(f"  Container: {self.config.get_azure_container() or '(not set)'}")
                print(f"  Default prefix: {self.config.get_azure_default_prefix() or '(empty)'}")
                return
            if len(parts) >= 4 and parts[1] == "set":
                key = parts[2]
                value = " ".join(parts[3:])
                if key == "connection":
                    self.config.set_azure_connection_string(value)
                    print("Azure connection string saved.")
                    return
                if key == "container":
                    self.config.set_azure_container(value)
                    print("Azure container saved.")
                    return
                if key == "prefix":
                    self.config.set_azure_default_prefix(value)
                    print("Azure default prefix saved.")
                    return
        print("Usage: config azure [show|set connection|container|prefix <value>]")

    def do_upload_albums(self, args):
        """Upload one or more albums to Azure storage.
        Usage:
          upload_albums [album1,album2,...] [--container NAME] [--prefix PFX] [-m]
        If no albums are specified, interactive album selection is shown.
        Flags:
          -m / --include-metadata  Include JSON metadata files
        """
        # Parse flags
        include_metadata = False
        container = None
        prefix = None
        tokens = args.split() if args else []
        albums_arg = None
        i = 0
        while i < len(tokens):
            tok = tokens[i]
            if tok in {"-m", "--include-metadata"}:
                include_metadata = True
                i += 1
            elif tok == "--container" and i + 1 < len(tokens):
                container = self._clean_cli_value(tokens[i + 1]).lower()
                i += 2
            elif tok == "--prefix" and i + 1 < len(tokens):
                prefix = self._clean_cli_value(tokens[i + 1])
                i += 2
            else:
                albums_arg = tok
                i += 1

        # Determine album list
        album_names: List[str] = []
        if albums_arg:
            if "," in albums_arg:
                album_names = [a.strip().strip('"') for a in albums_arg.split(",") if a.strip()]
            else:
                album_names = [albums_arg.strip('"')]
        else:
            album_names = self._interactive_album_selection()
            if not album_names:
                print("No albums selected.")
                return

        print("\nStarting upload...")

        def album_progress(current, total, album_name):
            print(f"\n[{current}/{total}] Uploading album: {album_name}")

        def file_progress(current, total, album_name):
            percent = (current / total * 100) if total > 0 else 0
            bar_length = 40
            filled = int(bar_length * current / total) if total > 0 else 0
            bar = "█" * filled + "░" * (bar_length - filled)
            print(f"\r  {bar} {percent:.1f}% ({current}/{total} files)", end="", flush=True)

        target = UploadTarget(provider="azure", container=container, prefix=(prefix or ""))
        stats = self.explorer.upload_albums(
            album_names,
            target=target,
            include_metadata=include_metadata,
            progress_callback=album_progress,
            file_progress_callback=file_progress,
        )
        self.formatter.print_upload_stats(stats)

    def do_upload_results(self, args):
        """Upload files from the last search results to Azure storage.
        Usage: upload_results [--container NAME] [--prefix PFX] [-m]
        """
        if not self.last_search_results:
            print("No search results available. Run 'search' first.")
            return
        include_metadata = False
        container = None
        prefix = None
        tokens = args.split() if args else []
        i = 0
        while i < len(tokens):
            tok = tokens[i]
            if tok in {"-m", "--include-metadata"}:
                include_metadata = True
                i += 1
            elif tok == "--container" and i + 1 < len(tokens):
                container = self._clean_cli_value(tokens[i + 1]).lower()
                i += 2
            elif tok == "--prefix" and i + 1 < len(tokens):
                prefix = self._clean_cli_value(tokens[i + 1])
                i += 2
            else:
                i += 1

        print("\nStarting upload from results...")

        def file_progress(current, total, item_name):
            percent = (current / total * 100) if total > 0 else 0
            bar_length = 40
            filled = int(bar_length * current / total) if total > 0 else 0
            bar = "█" * filled + "░" * (bar_length - filled)
            print(f"\r  {bar} {percent:.1f}% ({current}/{total} files)", end="", flush=True)

        target = UploadTarget(provider="azure", container=container, prefix=(prefix or ""))
        stats = self.explorer.upload_from_results(
            self.last_search_results,
            target=target,
            include_metadata=include_metadata,
            file_progress_callback=lambda c, t, fn: file_progress(c, t, fn),
        )
        print()
        self.formatter.print_upload_stats(stats)

    def do_upload_pattern(self, args):
        """Upload files matching a regex pattern to Azure storage.
        Usage: upload_pattern <PATTERN> [--container NAME] [--prefix PFX] [-m]
        """
        if not args:
            print("Usage: upload_pattern <PATTERN> [--container NAME] [--prefix PFX] [-m]")
            return
        tokens = args.split()
        pattern = tokens[0]
        include_metadata = False
        container = None
        prefix = None
        i = 1
        while i < len(tokens):
            tok = tokens[i]
            if tok in {"-m", "--include-metadata"}:
                include_metadata = True
                i += 1
            elif tok == "--container" and i + 1 < len(tokens):
                container = self._clean_cli_value(tokens[i + 1]).lower()
                i += 2
            elif tok == "--prefix" and i + 1 < len(tokens):
                prefix = self._clean_cli_value(tokens[i + 1])
                i += 2
            else:
                i += 1

        print("\nScanning and uploading...")

        def progress_callback(i, t):
            self.formatter.print_progress(i, t, "Scanning")

        def file_progress(current, total, item_name):
            percent = (current / total * 100) if total > 0 else 0
            bar_length = 40
            filled = int(bar_length * current / total) if total > 0 else 0
            bar = "█" * filled + "░" * (bar_length - filled)
            print(f"\r  {bar} {percent:.1f}% ({current}/{total} files)", end="", flush=True)

        target = UploadTarget(provider="azure", container=container, prefix=(prefix or ""))
        stats = self.explorer.upload_by_pattern(
            pattern,
            target=target,
            include_metadata=include_metadata,
            progress_callback=progress_callback,
            file_progress_callback=lambda c, t, _: file_progress(c, t, ""),
        )
        print()
        self.formatter.print_upload_stats(stats)

    def do_clear(self, arg):
        """Clear the screen.
        Usage: clear"""
        import os

        os.system("clear" if os.name == "posix" else "cls")

    def do_cache(self, arg):
        """Manage cache.
        Usage: cache clear - Clear all cached data
               cache info  - Show cache information"""
        if arg == "clear":
            self._album_cache = None
            self._file_cache = {}
            print("Cache cleared.")
        elif arg == "info":
            album_cached = "Yes" if self._album_cache else "No"
            file_cache_size = len(self._file_cache)
            print(f"Album cache loaded: {album_cached}")
            print(f"File cache entries: {file_cache_size}")
        else:
            print("Usage: cache [clear|info]")

    def do_export(self, filename):
        """Export last results to a file.
        Usage: export <filename>
        Example: export results.txt
        Example: export metadata.json"""
        if not filename:
            print("Please provide a filename.")
            return

        if filename.endswith(".json") and self.last_metadata:
            with open(filename, "w") as f:
                json.dump(self.last_metadata, f, indent=2)
            print(f"Exported {len(self.last_metadata)} metadata entries to {filename}")
        elif self.last_search_results:
            with open(filename, "w") as f:
                for zip_name, matches in self.last_search_results.items():
                    f.write(f"\n{zip_name}:\n")
                    for match in matches:
                        f.write(f"  {match}\n")
            print(f"Exported search results to {filename}")
        else:
            print("No results to export. Run a search or metadata extraction first.")

    def do_export_albums(self, args):
        """Export one or more albums to a directory.
        Usage: export_albums [album1,album2,...] [output_dir]

        If no albums specified, shows interactive selection.
        If no output directory specified, uses ./exported_albums

        Examples:
          export_albums                           # Interactive selection
          export_albums "Photos from 2023"        # Export single album
          export_albums "Photos from 2023,Bali"   # Export multiple albums
          export_albums "Photos from 2023" /path/to/output
        """
        parts = args.split(maxsplit=1) if args else []

        # Parse arguments
        album_names = []
        output_dir = "./exported_albums"

        if parts:
            if "," in parts[0]:
                # Multiple albums specified
                album_names = [a.strip().strip('"') for a in parts[0].split(",")]
            else:
                # Single album or interactive mode trigger
                first_arg = parts[0].strip('"')
                # Check if it's an album name or output directory
                if self._album_cache and first_arg in self._album_cache:
                    album_names = [first_arg]
                elif not first_arg.startswith(".") and not first_arg.startswith("/"):
                    album_names = [first_arg]
                else:
                    output_dir = first_arg

            if len(parts) > 1:
                output_dir = parts[1]

        # If no albums specified, show interactive selection
        if not album_names:
            album_names = self._interactive_album_selection()
            if not album_names:
                print("No albums selected.")
                return

        # Ensure album cache is loaded
        if not self._album_cache:
            print("Loading album information...")
            data = self.explorer.list_folders()
            self._album_cache = data["album_folders"]

        # Validate album names
        valid_albums = []
        for album in album_names:
            if album in self._album_cache:
                valid_albums.append(album)
            else:
                print(f"Warning: Album '{album}' not found, skipping.")

        if not valid_albums:
            print("No valid albums to export.")
            return

        # Confirm export
        print(f"\nReady to export {len(valid_albums)} album(s) to: {output_dir}")
        for album in valid_albums:
            stats = self._album_cache[album]
            total_files = stats["images"] + stats["videos"]
            print(f"  - {album} ({total_files} files)")

        confirm = input("\nProceed with export? (y/N): ")
        if confirm.lower() != "y":
            print("Export cancelled.")
            return

        # Perform export
        print("\nStarting export...")

        def album_progress(current, total, album_name):
            print(f"\n[{current}/{total}] Exporting album: {album_name}")

        def file_progress(current, total, album_name):
            percent = (current / total * 100) if total > 0 else 0
            bar_length = 40
            filled = int(bar_length * current / total) if total > 0 else 0
            bar = "█" * filled + "░" * (bar_length - filled)
            print(f"\r  {bar} {percent:.1f}% ({current}/{total} files)", end="", flush=True)

        stats = self.explorer.export_albums(
            valid_albums, output_dir, progress_callback=album_progress, file_progress_callback=file_progress
        )

        self.formatter.print_export_stats(stats)

    def _interactive_album_selection(self):
        """Interactive album selection interface."""
        if not self._album_cache:
            print("Loading album information...")
            data = self.explorer.list_folders()
            self._album_cache = data["album_folders"]

        # Sort albums by name
        sorted_albums = sorted(self._album_cache.keys())

        print("\nSelect albums to export (use numbers, ranges, or 'all'):")
        print("-" * 60)

        # Display albums with numbers
        for i, album in enumerate(sorted_albums, 1):
            stats = self._album_cache[album]
            total = stats["images"] + stats["videos"]
            print(f"{i:3d}. {album:<40} ({total:>5} files)")

        print("\nExamples: 1,3,5 | 1-5 | 1-5,10,15-20 | all")
        selection = input("Your selection: ").strip()

        if not selection:
            return []

        if selection.lower() == "all":
            return sorted_albums

        # Parse selection
        selected_albums = []
        try:
            parts = selection.split(",")
            for part in parts:
                part = part.strip()
                if "-" in part:
                    # Range
                    start, end = part.split("-")
                    start_idx = int(start.strip()) - 1
                    end_idx = int(end.strip()) - 1
                    for idx in range(start_idx, end_idx + 1):
                        if 0 <= idx < len(sorted_albums):
                            selected_albums.append(sorted_albums[idx])
                else:
                    # Single number
                    idx = int(part) - 1
                    if 0 <= idx < len(sorted_albums):
                        selected_albums.append(sorted_albums[idx])
        except (ValueError, IndexError):
            print("Invalid selection format.")
            return []

        # Remove duplicates while preserving order
        seen = set()
        unique_albums = []
        for album in selected_albums:
            if album not in seen:
                seen.add(album)
                unique_albums.append(album)

        return unique_albums

    def do_info(self, arg):
        """Show information about the collection.
        Usage: info"""
        print(f"Zip directory: {self.explorer.zip_directory}")
        print(f"Total zip files: {len(self.explorer.zip_files)}")

        total_size = sum(zf.stat().st_size for zf in self.explorer.zip_files)
        print(f"Total size: {total_size / (1024**3):.1f} GB")

        if self.current_zip:
            print(f"Current zip: #{self.current_zip}")
        if self.current_album:
            print(f"Current album: {self.current_album}")

    def do_quit(self, arg):
        """Exit the interactive shell.
        Usage: quit"""
        print("Goodbye!")
        return True

    def do_exit(self, arg):
        """Exit the interactive shell.
        Usage: exit"""
        return self.do_quit(arg)

    def do_EOF(self, arg):
        """Handle Ctrl-D."""
        print()  # New line
        return self.do_quit(arg)

    def complete_explore(self, text, line, begidx, endidx):
        """Tab completion for explore command."""
        return [str(i) for i in range(1, len(self.explorer.zip_files) + 1) if str(i).startswith(text)]

    def complete_extract(self, text, line, begidx, endidx):
        """Tab completion for extract command."""
        parts = line.split()
        if len(parts) == 2:  # Completing zip number
            return self.complete_explore(text, line, begidx, endidx)
        return []

    def complete_cd(self, text, line, begidx, endidx):
        """Tab completion for cd command."""
        if not self._album_cache:
            # Load albums if not cached
            data = self.explorer.list_folders()
            self._album_cache = data["album_folders"]

        # Return matching album names
        albums = [
            f'"{name}"' if " " in name else name
            for name in self._album_cache.keys()
            if name.lower().startswith(text.lower())
        ]
        return albums

    def complete_export_albums(self, text, line, begidx, endidx):
        """Tab completion for export_albums command."""
        if not self._album_cache:
            # Load albums if not cached
            data = self.explorer.list_folders()
            self._album_cache = data["album_folders"]

        # Return matching album names
        albums = [
            f'"{name}"' if " " in name else name
            for name in self._album_cache.keys()
            if name.lower().startswith(text.lower())
        ]
        return albums

    def complete_cache(self, text, line, begidx, endidx):
        """Tab completion for cache command."""
        commands = ["clear", "info"]
        return [cmd for cmd in commands if cmd.startswith(text)]

    def emptyline(self):
        """Do nothing on empty line."""
        pass

    def default(self, line):
        """Handle unknown commands."""
        print(f"Unknown command: {line.split()[0]}")
        print("Type 'help' for available commands.")


def run_interactive(zip_directory: str):
    """Run the interactive shell."""
    try:
        shell = GooglePhotosInteractiveShell(zip_directory)
        shell.cmdloop()
    except KeyboardInterrupt:
        print("\nUse 'quit' to exit.")
        run_interactive(zip_directory)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
