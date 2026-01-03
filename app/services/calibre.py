import subprocess
import json
import os
from typing import List, Dict, Optional
from app.models.settings import Setting


class CalibreService:
    """Service for interacting with Calibre library via calibredb CLI."""

    def __init__(self):
        self.calibredb_path = None
        self.library_path = None
        self._load_settings()

    def _load_settings(self):
        """Load Calibre paths from settings."""
        self.calibredb_path = Setting.get('calibredb_path')
        self.library_path = Setting.get('calibre_library_path')

    def _run_calibredb(self, args: List[str]) -> str:
        """Run calibredb command and return output."""
        if not self.calibredb_path or not self.library_path:
            raise ValueError("Calibre paths not configured")

        cmd = [self.calibredb_path] + args + ['--library-path', self.library_path]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True
            )
            return result.stdout
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"calibredb command failed: {e.stderr}")

    def list_books(self, limit: Optional[int] = None, offset: int = 0) -> List[Dict]:
        """List books in the Calibre library.

        Args:
            limit: Maximum number of books to return
            offset: Number of books to skip

        Returns:
            List of book dictionaries with metadata
        """
        args = ['list', '--for-machine', '--fields', 'id,title,authors,formats,tags,series,series_index,publisher,pubdate,isbn,comments']

        if limit:
            args.extend(['--limit', str(limit)])

        output = self._run_calibredb(args)
        books = json.loads(output) if output else []

        # Apply offset manually since calibredb doesn't have native offset
        if offset:
            books = books[offset:]

        return books

    def get_book(self, book_id: int) -> Optional[Dict]:
        """Get detailed information about a specific book.

        Args:
            book_id: Calibre book ID

        Returns:
            Book dictionary with metadata or None if not found
        """
        args = ['list', '--for-machine', '--fields', 'id,title,authors,formats,tags,series,series_index,publisher,pubdate,isbn,comments', '--search', f'id:{book_id}']
        output = self._run_calibredb(args)
        books = json.loads(output) if output else []

        return books[0] if books else None

    def search_books(self, query: str) -> List[Dict]:
        """Search for books in the library.

        Args:
            query: Search query (uses Calibre's search syntax)

        Returns:
            List of matching books
        """
        args = ['list', '--for-machine', '--fields', 'id,title,authors,formats,tags,series,series_index,publisher,pubdate,isbn,comments', '--search', query]
        output = self._run_calibredb(args)
        return json.loads(output) if output else []

    def get_book_path(self, book_id: int) -> Optional[str]:
        """Get the library path for a specific book.

        Args:
            book_id: Calibre book ID

        Returns:
            Relative path to book directory or None if not found
        """
        # Use calibredb list without field restrictions to get default fields including path
        args = ['list', '--for-machine', '--search', f'id:{book_id}']
        output = self._run_calibredb(args)
        books = json.loads(output) if output else []

        if books and 'path' in books[0]:
            return books[0]['path']

        return None

    def get_cover_path(self, book_id: int) -> Optional[str]:
        """Get the file path to a book's cover image.

        Args:
            book_id: Calibre book ID

        Returns:
            Absolute path to cover image or None if not found
        """
        book_path = self.get_book_path(book_id)
        if not book_path:
            return None

        # Calibre stores covers in the book's directory
        # Try multiple formats in order of preference
        book_dir = os.path.join(self.library_path, book_path)

        for cover_name in ['cover.jpg', 'cover.jpeg', 'cover.png']:
            cover_path = os.path.join(book_dir, cover_name)
            if os.path.isfile(cover_path):
                return cover_path

        return None

    def get_book_count(self) -> int:
        """Get total number of books in library."""
        books = self.list_books()
        return len(books)

    def export_book(self, book_id: int, output_dir: str) -> str:
        """Export a book file to a directory.

        Args:
            book_id: Calibre book ID
            output_dir: Directory to export to

        Returns:
            Path to exported file
        """
        args = ['export', str(book_id), '--to-dir', output_dir, '--single-dir']
        self._run_calibredb(args)
        return output_dir

    def verify_installation(self) -> Dict[str, bool]:
        """Verify that Calibre is properly configured.

        Returns:
            Dict with 'calibredb_exists' and 'library_exists' flags
        """
        import os

        return {
            'calibredb_exists': os.path.isfile(self.calibredb_path) if self.calibredb_path else False,
            'library_exists': os.path.isdir(self.library_path) if self.library_path else False,
        }
