"""
Format utility functions for Folio.
Handles author name normalization and file format detection.
"""


def normalize_author_name(author_str):
    """Convert 'LastName, FirstName' or 'LastName| FirstName' to 'FirstName LastName'."""
    author_str = author_str.strip()
    if not author_str:
        return None

    # Handle pipe format: "LastName| FirstName" or "LastName|FirstName"
    if '|' in author_str:
        parts = author_str.split('|', 1)
        if len(parts) == 2:
            last_name = parts[0].strip()
            first_name = parts[1].strip()
            if first_name and last_name:
                return f"{first_name} {last_name}"

    # Handle comma format: "LastName, FirstName" or "LastName,FirstName"
    if ', ' in author_str:
        parts = author_str.split(', ', 1)
        if len(parts) == 2:
            last_name = parts[0].strip()
            first_name = parts[1].strip()
            if first_name and last_name:
                return f"{first_name} {last_name}"
    elif author_str.count(',') == 1 and not author_str.startswith(','):
        parts = author_str.split(',', 1)
        if len(parts) == 2:
            last_name = parts[0].strip()
            first_name = parts[1].strip()
            if first_name and last_name:
                return f"{first_name} {last_name}"

    # If no conversion needed, return as-is
    return author_str


def get_last_name_for_sort(author):
    """Extract last name for sorting purposes."""
    if not author:
        return ''
    parts = author.split()
    return parts[-1].lower() if parts else ''


def format_file_size(size_bytes):
    """Format file size in human-readable format."""
    if size_bytes is None or size_bytes == 0:
        return "Unknown"
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


def detect_format_from_extension(filename):
    """Detect ebook format from file extension."""
    if not filename:
        return None
    ext = filename.lower().split('.')[-1]
    format_map = {
        'epub': 'EPUB',
        'kepub': 'KEPUB',
        'mobi': 'MOBI',
        'azw': 'AZW',
        'azw3': 'AZW3',
        'pdf': 'PDF',
        'txt': 'TXT',
        'html': 'HTML',
        'htm': 'HTML',
        'cbz': 'CBZ',
        'cbr': 'CBR',
    }
    # Special case for kepub.epub
    if filename.lower().endswith('.kepub.epub'):
        return 'KEPUB'
    return format_map.get(ext)


EBOOK_EXTENSIONS = {
    '.epub', '.mobi', '.azw', '.azw3', '.pdf', '.txt',
    '.kepub', '.kepub.epub', '.cbz', '.cbr', '.fb2', '.lit'
}


def is_ebook_file(filename):
    """Check if filename is a supported ebook format."""
    if not filename:
        return False
    lower = filename.lower()
    # Check for kepub.epub first
    if lower.endswith('.kepub.epub'):
        return True
    for ext in EBOOK_EXTENSIONS:
        if lower.endswith(ext):
            return True
    return False
