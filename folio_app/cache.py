"""
ORPHANED MODULE - This file is not used. See folio_app/__init__.py for details.
Duplicate of caching code in folio.py which is actually used.

Original description:
Caching infrastructure for Folio.
Provides API response caching and cover metadata caching.
"""
import os
import time
import sqlite3
import threading

from .config import get_calibre_library


class APICache:
    """Simple in-memory cache with TTL for API responses."""

    def __init__(self):
        self._cache = {}
        self._lock = threading.Lock()

    def get(self, key):
        """Get cached value if not expired."""
        with self._lock:
            if key in self._cache:
                value, expiry = self._cache[key]
                if time.time() < expiry:
                    return value
                else:
                    del self._cache[key]
            return None

    def set(self, key, value, ttl_seconds):
        """Cache a value with TTL."""
        with self._lock:
            expiry = time.time() + ttl_seconds
            self._cache[key] = (value, expiry)

    def clear(self, pattern=None):
        """Clear cache entries, optionally matching a pattern."""
        with self._lock:
            if pattern is None:
                self._cache.clear()
            else:
                keys_to_delete = [k for k in self._cache if pattern in k]
                for key in keys_to_delete:
                    del self._cache[key]

    def stats(self):
        """Get cache statistics."""
        with self._lock:
            now = time.time()
            valid_count = sum(1 for _, (_, expiry) in self._cache.items() if now < expiry)
            return {
                'total_entries': len(self._cache),
                'valid_entries': valid_count,
                'keys': list(self._cache.keys())
            }


class CoverCache:
    """Cache book cover metadata to avoid DB hits on every cover request.

    This solves the issue where many concurrent cover requests cause SQLite
    contention, leading to random timeouts and inconsistent cover loading.
    """

    def __init__(self, ttl_seconds=300):
        self._cache = {}
        self._lock = threading.Lock()
        self._ttl = ttl_seconds
        self._expiry = 0
        self._loading = False

    def get(self, book_id):
        """Get cached cover info for a book."""
        with self._lock:
            if time.time() > self._expiry:
                return None
            return self._cache.get(book_id)

    def get_all(self):
        """Get all cached cover info (for bulk lookups)."""
        with self._lock:
            if time.time() > self._expiry:
                return None
            return self._cache.copy()

    def load_all(self, force=False):
        """Load all book cover metadata from DB into cache.

        Called once on startup and periodically refreshed.
        Uses a loading flag to prevent concurrent loads.
        """
        with self._lock:
            if self._loading:
                return False
            if not force and time.time() < self._expiry:
                return True
            self._loading = True

        try:
            library_path = get_calibre_library()
            db_path = os.path.join(library_path, 'metadata.db')

            if not os.path.exists(db_path):
                return False

            conn = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True, timeout=30.0)
            conn.row_factory = sqlite3.Row

            cursor = conn.cursor()
            cursor.execute("SELECT id, path, has_cover FROM books")
            rows = cursor.fetchall()
            conn.close()

            new_cache = {}
            for row in rows:
                new_cache[row['id']] = {
                    'path': row['path'],
                    'has_cover': bool(row['has_cover'])
                }

            with self._lock:
                self._cache = new_cache
                self._expiry = time.time() + self._ttl
                self._loading = False

            print(f"📦 Cover cache loaded: {len(new_cache)} books")
            return True

        except Exception as e:
            print(f"❌ Cover cache load error: {e}")
            with self._lock:
                self._loading = False
            return False

    def invalidate(self, book_id=None):
        """Invalidate cache for a specific book or all books."""
        with self._lock:
            if book_id is not None:
                self._cache.pop(book_id, None)
            else:
                self._expiry = 0


# Global cache instances
api_cache = APICache()
cover_cache = CoverCache(ttl_seconds=300)
