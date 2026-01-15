"""
File utility functions for Folio.
"""
import os
import time
import hashlib
from pathlib import Path


def compute_file_hash(filepath):
    """Compute MD5 hash of a file."""
    try:
        hash_md5 = hashlib.md5()
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()
    except Exception as e:
        print(f"⚠️  Failed to compute hash for {filepath}: {e}")
        return None


def list_directories(path):
    """List directories at the given path."""
    try:
        path = os.path.expanduser(path)
        path = os.path.abspath(path)

        if not os.path.exists(path):
            return {'error': 'Path does not exist', 'path': path}

        if not os.path.isdir(path):
            return {'error': 'Path is not a directory', 'path': path}

        parent = str(Path(path).parent)

        entries = []
        try:
            for entry in sorted(os.listdir(path)):
                entry_path = os.path.join(path, entry)
                if os.path.isdir(entry_path):
                    is_calibre_library = os.path.exists(os.path.join(entry_path, 'metadata.db'))
                    entries.append({
                        'name': entry,
                        'path': entry_path,
                        'is_calibre_library': is_calibre_library
                    })
        except PermissionError:
            return {'error': 'Permission denied', 'path': path}

        return {
            'path': path,
            'parent': parent,
            'directories': entries
        }
    except Exception as e:
        return {'error': str(e), 'path': path}


def is_file_mature(filepath, min_age_seconds=5):
    """Check if a file has been stable (not modified) for min_age_seconds.

    This helps avoid importing files that are still being downloaded/written.
    """
    try:
        mtime = os.path.getmtime(filepath)
        age = time.time() - mtime
        return age >= min_age_seconds
    except Exception:
        return False


def format_file_size(size_bytes):
    """Format file size in human-readable format."""
    if size_bytes is None:
        return "Unknown"
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"
