"""
Database connection management for Folio.
"""
import os
import sqlite3
from contextlib import contextmanager

from ..config import get_calibre_library, get_folio_db_path


@contextmanager
def get_folio_db_connection(readonly=False):
    """Get a connection to the folio database as a context manager.

    Args:
        readonly: If True, open in read-only mode

    Yields:
        sqlite3.Connection: Database connection that will be automatically closed

    Example:
        with get_folio_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM table")
    """
    conn = None
    try:
        db_path = get_folio_db_path()

        if readonly:
            conn = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True, timeout=10.0)
        else:
            conn = sqlite3.connect(db_path, timeout=10.0)

        conn.row_factory = sqlite3.Row
        yield conn
    finally:
        if conn:
            conn.close()


@contextmanager
def get_calibre_db_connection(readonly=True):
    """Get a connection to the Calibre metadata database as a context manager.

    Args:
        readonly: If True, open in read-only mode (default for safety)

    Yields:
        sqlite3.Connection: Database connection that will be automatically closed

    Example:
        with get_calibre_db_connection(readonly=True) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM books")
    """
    conn = None
    try:
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

        yield conn
    finally:
        if conn:
            conn.close()
