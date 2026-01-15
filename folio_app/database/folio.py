"""
Folio database schema and initialization.
"""
import sqlite3

from ..config import get_folio_db_path


def init_folio_db():
    """Initialize the folio database with required tables."""
    db_path = get_folio_db_path()
    conn = None
    try:
        conn = sqlite3.connect(db_path, timeout=10.0)
        cursor = conn.cursor()

        # Create reading_list table for multi-user support
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS reading_list (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user TEXT NOT NULL,
                book_id INTEGER NOT NULL,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user, book_id)
            )
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_reading_list_user
            ON reading_list(user)
        """)

        # Create requests table for book requests (shared across all users)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                external_id TEXT UNIQUE,
                title TEXT NOT NULL,
                author TEXT,
                year INTEGER,
                description TEXT,
                image TEXT,
                requested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                actioned_at TIMESTAMP
            )
        """)

        # Create import_history table for tracking imported files
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS import_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_path TEXT NOT NULL,
                file_hash TEXT NOT NULL,
                file_size INTEGER,
                book_id INTEGER,
                imported_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(file_path),
                UNIQUE(file_hash)
            )
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_import_history_file_path
            ON import_history(file_path)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_import_history_file_hash
            ON import_history(file_hash)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_import_history_book_id
            ON import_history(book_id)
        """)

        # Create kobo_tokens table for Kobo sync authentication
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS kobo_tokens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user TEXT NOT NULL UNIQUE,
                auth_token TEXT NOT NULL UNIQUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_used TIMESTAMP
            )
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_kobo_tokens_auth_token
            ON kobo_tokens(auth_token)
        """)

        # Create kobo_sync_state table for tracking sync progress
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS kobo_sync_state (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user TEXT NOT NULL,
                book_id INTEGER NOT NULL,
                synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_modified TIMESTAMP,
                is_archived INTEGER DEFAULT 0,
                UNIQUE(user, book_id)
            )
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_kobo_sync_state_user
            ON kobo_sync_state(user)
        """)

        conn.commit()
        print(f"✅ Folio database initialized at {db_path}")
        return True
    except Exception as e:
        print(f"❌ Failed to initialize folio database: {e}")
        return False
    finally:
        if conn:
            conn.close()
