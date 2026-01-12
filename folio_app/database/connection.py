"""
Database connection management for Folio.
"""
import os
import sqlite3

from ..config import get_calibre_library, get_folio_db_path


def get_folio_db_connection(readonly=False):
    """Get a connection to the folio database."""
    db_path = get_folio_db_path()

    if readonly:
        conn = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True, timeout=10.0)
    else:
        conn = sqlite3.connect(db_path, timeout=10.0)

    conn.row_factory = sqlite3.Row
    return conn


def get_calibre_db_connection(readonly=True):
    """Get a connection to the Calibre metadata database.

    Args:
        readonly: If True, open in read-only mode (default for safety)

    Returns:
        sqlite3.Connection with Row factory
    """
    library_path = get_calibre_library()
    db_path = os.path.join(library_path, 'metadata.db')

    if not os.path.exists(db_path):
        raise FileNotFoundError(f"Calibre database not found at {db_path}")

    if readonly:
        conn = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True, timeout=30.0)
    else:
        conn = sqlite3.connect(db_path, timeout=30.0)

    conn.row_factory = sqlite3.Row

    # Register custom function for title_sort fallback
    def title_sort_fallback(title, title_sort):
        return title_sort if title_sort else title

    conn.create_function("title_sort_fallback", 2, title_sort_fallback)

    return conn
