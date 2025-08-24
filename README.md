# Google Photos Takeout Explorer

A command-line tool/shell to explore and extract information from Google Photos Takeout zip files without extracting them all at once. Perfect for managing large takeout exports (100+ GB) that would be impractical to fully extract.

## What is Google Takeout?
Google Takeout lets you export a copy of your data from Google products, including Google Photos, as downloadable archives for backup or migration. See Google’s official resources: [Download your data (Google Account Help)](https://support.google.com/accounts/answer/3024190) and [Google Takeout](https://takeout.google.com/).

## How to export your Google Photos with Google Takeout
1. Go to [Google Takeout](https://takeout.google.com/) and sign in.
2. Click "Deselect all", then enable "Google Photos".
3. Optional: select specific albums or years via "All photo albums included".
4. Click "Next step", choose delivery method, frequency, file type (.zip/.tgz) and max archive size.
5. Click "Create export". You’ll receive an email when it’s ready; large libraries can take hours or days.

Notes
- Exports come as one or more archives up to the size you selected.
- Many items include a companion .json file with metadata (e.g., taken time, location). This tool reads those alongside your media.
- Exporting does not delete anything from Google Photos.

## Features

- **Interactive Mode** - New! Interactive shell with tab completion and session state
- **Album Export** - New! Export entire albums with interactive selection or batch mode
- **Non-destructive exploration** - Read zip contents without extraction
- **Batch processing** - Work across 150+ zip files seamlessly  
- **Metadata extraction** - Export photo metadata to JSON for analysis
- **Smart searching** - Use regex patterns to find specific files
- **Date analysis** - Discover the time range of your photo collection
- **Selective extraction** - Extract only the files you need
 - **Thumbnail uploads** - New! Generate thumbnails on upload (512×512 max) with filenames prefixed by `thumb-`, or upload thumbnails only

## Installation

Install dependencies:

```bash
pip install -r requirements.txt

# Make the script executable
chmod +x gphoto_explorer.py
```

Notes:
- Thumbnail generation requires Pillow, which is included in `requirements.txt`.

## Usage

### Interactive Mode (NEW!)

Launch an interactive shell for exploring your photos:

```bash
python gphoto_explorer.py /path/to/zip/directory --interactive
# or
python gphoto_explorer.py /path/to/zip/directory -i
```

#### Interactive Commands

Once in interactive mode, you have access to these commands:

- `list` - List all zip files
- `ls [-a]` - Context-aware list. At root: lists zip files. In an album: lists files in the current album (use `-a` to include metadata files)
- `explore <N>` - Explore zip file number N
- `search <pattern>` - Search for files matching regex pattern
- `folders` or `albums` - List all albums with photo/video counts
- `cd <album>` - Change context to specific album
- `pwd` - Show current album context
- `metadata <pattern> [output]` - Extract metadata matching pattern
- `daterange` - Analyze date range of all photos
- `extract <N> <file> [dir]` - Extract specific file from zip N
- `export <filename>` - Export last results to file
- `export_albums [albums] [dir]` - Export albums (interactive selection if no args)
- `config azure [show|set connection|container|prefix <value>]` - Configure Azure Storage
- `upload_albums [albums] [--container NAME] [--prefix PFX] [-m]` - Upload one or more albums to Azure (interactive selection if no args)
- `upload_results [--container NAME] [--prefix PFX] [-m]` - Upload files from last `search` results
- `upload_pattern <pattern> [--container NAME] [--prefix PFX] [-m]` - Upload files matching a regex
- `cache [clear|info]` - Manage cached data
- `info` - Show collection information
- `clear` - Clear screen
- `help [command]` - Get help
- `quit` or `exit` - Exit interactive mode

#### Interactive Features

- **Tab Completion**: Press Tab to complete commands, album names, and arguments
- **Command History**: Use arrow keys to navigate command history
- **Session State**: The shell remembers your last search, current album, etc.
- **Progress Indicators**: Real-time progress for long operations
- **Caching**: Album and folder data is cached for faster subsequent access

### Command-Line Mode (Original)

All original command-line functionality remains available:

### Basic Command Structure

```bash
python gphoto_explorer.py /path/to/zip/directory [options]
```

### Available Options

#### List All Zip Files
```bash
python gphoto_explorer.py ~/GooglePhotosDownload --list
```
Shows all zip files with their sizes in the specified directory.

#### Explore a Specific Zip
```bash
python gphoto_explorer.py ~/GooglePhotosDownload --explore 1
```
Displays detailed contents of a specific zip file (by index number):
- Total file count
- Breakdown by type (images, videos, JSON metadata, other)
- Sample file paths to understand structure

#### Search Across All Zips
```bash
python gphoto_explorer.py ~/GooglePhotosDownload --search "IMG_.*\.jpg"
```
Search for files matching a regex pattern across all zip files. Shows matches grouped by zip file.

Common search patterns:
- `"IMG_.*\.jpg"` - Find all IMG photos
- `".*2023.*"` - Find files from 2023
- `".*\.mp4"` - Find all MP4 videos
- `".*Barcelona.*"` - Find files with "Barcelona" in the path

#### Extract Metadata
```bash
python gphoto_explorer.py ~/GooglePhotosDownload --metadata ".*\.json" --output metadata.json
```
Extract and consolidate metadata from JSON files matching a pattern. The output includes:
- Photo titles and descriptions
- Creation and taken timestamps
- Geo location data
- View counts
- Google Photos URLs
- Source zip and file information

#### Analyze Date Range
```bash
python gphoto_explorer.py ~/GooglePhotosDownload --date-range
```
Analyzes all photo metadata to determine:
- Total photos with date information
- Earliest photo date
- Latest photo date
- Processing errors (if any)

#### Extract Specific Files
```bash
python gphoto_explorer.py ~/GooglePhotosDownload --extract 1 "Takeout/Google Photos/2023/IMG_1234.jpg" --extract-to ./extracted
```
Extract individual files from a zip without extracting everything. Useful for retrieving specific photos or videos.

#### Export Albums
```bash
# Export single album
python gphoto_explorer.py ~/GooglePhotosDownload --export-albums "Photos from 2023"

# Export multiple albums
python gphoto_explorer.py ~/GooglePhotosDownload --export-albums "Photos from 2023,Bali,Japan" --export-to /path/to/output

# Export albums with spaces in names
python gphoto_explorer.py ~/GooglePhotosDownload --export-albums "Costa Rica Surf,New Zealand"
```
Export complete albums from across all zip files. The tool automatically finds all files belonging to each album and extracts them with proper folder structure.

#### Configure Azure and Upload

```bash
# Configure Azure (can also use environment variables)
python gphoto_explorer.py ~/GooglePhotosDownload \
  --azure-set-connection "DefaultEndpointsProtocol=...;AccountName=...;AccountKey=...;EndpointSuffix=core.windows.net" \
  --azure-set-container my-container \
  --azure-set-prefix google-photos/

# Upload albums (comma-separated)
python gphoto_explorer.py ~/GooglePhotosDownload \
  --upload-albums "Photos from 2023,Bali" \
  --upload-prefix backups/2025-01-01/ \
  --upload-include-metadata

# Upload files by pattern (exclude metadata by default)
python gphoto_explorer.py ~/GooglePhotosDownload \
  --upload-pattern ".*2020.*\\.(jpg|jpeg|png)$" \
  --upload-prefix ad-hoc/
```

#### Thumbnail Uploads

You can generate thumbnails during upload. Thumbnails use the same folder as the original and are saved with a `thumb-` filename prefix (e.g., `IMG_1234.jpg` → `thumb-IMG_1234.jpg`). Default thumbnail size is up to 512×512 while preserving aspect ratio.

CLI examples:

```bash
# Upload albums and include thumbnails alongside originals
python gphoto_explorer.py ~/GooglePhotosDownload \
  --upload-albums "Photos from 2023" \
  --upload-include-thumbnails

# Upload only thumbnails (skip originals)
python gphoto_explorer.py ~/GooglePhotosDownload \
  --upload-albums "Photos from 2023" \
  --upload-thumbnails-only

# Pattern upload with thumbnails
python gphoto_explorer.py ~/GooglePhotosDownload \
  --upload-pattern ".*\\.(jpg|jpeg|png)$" \
  --upload-include-thumbnails
```

Interactive mode examples:

- `upload_albums "Photos from 2023" --thumbs`
- `upload_albums "Photos from 2023" --thumbs-only`
- `upload_pattern ".*\\.jpg" --thumbs`
- `upload_results --thumbs-only`

Environment variables (override stored config):

- `AZURE_STORAGE_CONNECTION_STRING`
- `AZURE_STORAGE_CONTAINER`
- `AZURE_STORAGE_PREFIX`

Notes:
- Upload destination path is `<prefix>/<album>/<relative_path>` for album uploads, or `<prefix>/<archive_path>` for pattern/search uploads.
- Only Azure is supported today, but the design allows additional providers in the future.
 - Thumbnails are saved next to originals with `thumb-` prefix; for album uploads, thumbnails are placed under the album folder.

## Examples

### Interactive Mode Session Example

```bash
$ python gphoto_explorer.py ~/GooglePhotosDownload -i

╔══════════════════════════════════════════════════════════════════╗
║         Google Photos Takeout Explorer - Interactive Mode        ║
╠══════════════════════════════════════════════════════════════════╣
║  Type 'help' for commands or 'help <command>' for details        ║
║  Tab completion available for commands and arguments             ║
║  Type 'quit' or 'exit' to leave                                  ║
╚══════════════════════════════════════════════════════════════════╝

gphoto> folders
Scanning all zip files for folders and counting files...
[Shows all albums with photo/video counts]

gphoto> cd "Photos from 2023"
Changed to album: Photos from 2023
  Images: 1234, Videos: 56

gphoto [Photos from 2023]> search IMG_.*
Searching for pattern: IMG_.*
[Shows matching files in current album context]

gphoto [Photos from 2023]> export results.txt
Exported search results to results.txt

gphoto [Photos from 2023]> export_albums
Select albums to export (use numbers, ranges, or 'all'):
[Shows numbered list of all albums]
Your selection: 1-5,10
[Exports selected albums with progress bars]

gphoto [Photos from 2023]> quit
Goodbye!
```

### Command-Line Examples

#### Find all photos from a specific trip
```bash
# Search for photos in a specific album
python gphoto_explorer.py ~/GooglePhotosDownload --search "Eurfrica.*\.jpg"
```

### Extract all metadata for analysis
```bash
# Extract all JSON metadata files
python gphoto_explorer.py ~/GooglePhotosDownload --metadata ".*\.json" --output all_metadata.json

# Extract metadata for specific year
python gphoto_explorer.py ~/GooglePhotosDownload --metadata ".*2023.*\.json" --output metadata_2023.json
```

### Explore your collection
```bash
# See what's in the first few zips
python gphoto_explorer.py ~/GooglePhotosDownload --explore 1
python gphoto_explorer.py ~/GooglePhotosDownload --explore 2

# Get overview of date range
python gphoto_explorer.py ~/GooglePhotosDownload --date-range
```

### Extract specific photos
```bash
# First find the file
python gphoto_explorer.py ~/GooglePhotosDownload --search "IMG_1234"

# Then extract it from the appropriate zip
python gphoto_explorer.py ~/GooglePhotosDownload --extract 5 "Takeout/Google Photos/2023/IMG_1234.jpg"
```

## Output Formats

### Metadata JSON Structure
When extracting metadata, each entry contains:
```json
{
  "title": "IMG_1234.jpg",
  "description": "Barcelona trip",
  "imageViews": "42",
  "creationTime": {
    "timestamp": "1234567890",
    "formatted": "Jan 1, 2023, 12:00:00 AM UTC"
  },
  "photoTakenTime": {
    "timestamp": "1234567890",
    "formatted": "Jan 1, 2023, 12:00:00 AM UTC"
  },
  "geoData": {
    "latitude": 41.3851,
    "longitude": 2.1734,
    "altitude": 0.0
  },
  "url": "https://photos.google.com/photo/...",
  "_source_zip": "takeout-20250810T142125Z-1-001.zip",
  "_source_file": "Takeout/Google Photos/..."
}
```

## Tips

1. **Start with `--list`** to understand your zip file structure
2. **Use `--explore`** on a few zips to understand the folder organization
3. **Use `--date-range`** to get an overview of your collection's timeline
4. **Extract metadata first** before deciding which files to extract
5. **Use regex patterns** for powerful searching across all zips
6. **Pipe output** to files for large result sets: `--search "pattern" > results.txt`

## Performance

- Processes 150+ zip files (300+ GB) without extraction
- Metadata extraction: ~500 files/second
- Search operations: ~1000 files/second
- Memory efficient - processes one zip at a time

## Limitations

- Requires enough RAM to hold one zip file's index in memory
- JSON metadata parsing expects Google Takeout format
- Date analysis relies on Google Photos metadata structure
 - Thumbnail generation supports common raster formats (JPEG/PNG/GIF/BMP/WebP). HEIC thumbnails are currently not generated; originals still upload.

## Error Handling

The tool will:
- Report if the specified directory doesn't exist
- Skip corrupted or unreadable JSON files
- Continue processing if individual files fail
- Report total errors at the end of operations

## Contributing

Contributions are welcome! Please read `CONTRIBUTING.md` for setup, coding guidelines, and the pull request process.

## Code of Conduct

We follow a Code of Conduct to foster an open and welcoming environment. See `CODE_OF_CONDUCT.md`.

## Security

If you discover a security vulnerability, please follow the instructions in `SECURITY.md` to report it responsibly.

## License

This project is licensed under the MIT License. See `LICENSE` for details.

## Disclaimer

- This project is not affiliated with or endorsed by Google.
- Use only with content you own and have the right to process.
- Respect all applicable laws and the terms of the services you use.

## Community and Support

- Found a bug or have an idea? Open an issue using our templates in `.github/ISSUE_TEMPLATE`.
- Want to contribute code or docs? See `CONTRIBUTING.md` and open a pull request.