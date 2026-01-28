"""
Library access and rendering helpers.
"""
import os
import sqlite3
from contextlib import contextmanager

from .cache import cover_cache
from .config import get_calibre_library
from .reading_list import get_reading_list_ids_for_user
from .utils.format import normalize_author_name
from .utils.text import escape_html


@contextmanager
def get_db_connection(readonly=False):
    """Get a connection to the Calibre metadata database as a context manager."""
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
            try:
                conn.execute("PRAGMA journal_mode=WAL")
            except Exception:
                pass

        conn.row_factory = sqlite3.Row

        try:
            conn.create_function("title_sort", 1, lambda s: s or "")
        except Exception:
            pass

        yield conn
    finally:
        if conn:
            conn.close()


def get_books(limit=50, offset=0, search=None, sort='recent'):
    """Get books from the Calibre database."""
    try:
        with get_db_connection(readonly=True) as conn:
            cursor = conn.cursor()

            if sort == 'title':
                order_clause = "ORDER BY b.sort"
            elif sort == 'author':
                order_clause = "ORDER BY authors, b.sort"
            else:
                order_clause = "ORDER BY b.timestamp DESC"

            query = """
                SELECT
                    b.id,
                    b.title,
                    b.sort,
                    b.timestamp,
                    b.pubdate,
                    b.series_index,
                    b.path,
                    b.has_cover,
                    GROUP_CONCAT(a.name, ' & ') as authors,
                    GROUP_CONCAT(t.name, ', ') as tags,
                    c.text as comments,
                    p.name as publisher,
                    s.name as series
                FROM books b
                LEFT JOIN books_authors_link bal ON b.id = bal.book
                LEFT JOIN authors a ON bal.author = a.id
                LEFT JOIN books_tags_link btl ON b.id = btl.book
                LEFT JOIN tags t ON btl.tag = t.id
                LEFT JOIN comments c ON b.id = c.book
                LEFT JOIN books_publishers_link bpl ON b.id = bpl.book
                LEFT JOIN publishers p ON bpl.publisher = p.id
                LEFT JOIN books_series_link bsl ON b.id = bsl.book
                LEFT JOIN series s ON bsl.series = s.id
            """

            if search:
                query += " WHERE b.title LIKE ? OR a.name LIKE ?"
                params = (f'%{search}%', f'%{search}%', limit, offset)
            else:
                params = (limit, offset)

            query += f" GROUP BY b.id {order_clause} LIMIT ? OFFSET ?"

            cursor.execute(query, params)
            rows = cursor.fetchall()

            book_ids = [row['id'] for row in rows]

            formats_map = {}
            if book_ids:
                placeholders = ','.join('?' * len(book_ids))
                cursor.execute(f"SELECT book, format FROM data WHERE book IN ({placeholders})", book_ids)
                for fmt_row in cursor.fetchall():
                    book_id = fmt_row['book']
                    if book_id not in formats_map:
                        formats_map[book_id] = []
                    formats_map[book_id].append(fmt_row['format'].upper())

            library_path = get_calibre_library()

            books = []
            for row in rows:
                formats = formats_map.get(row['id'], [])

                if 'KEPUB' not in formats and row['path']:
                    book_dir = os.path.join(library_path, row['path'])
                    if os.path.isdir(book_dir):
                        for filename in os.listdir(book_dir):
                            if filename.lower().endswith('.kepub'):
                                formats.append('KEPUB')
                                break

                authors_list = []
                seen_authors = set()

                if row['authors']:
                    authors_str = str(row['authors']).strip()
                    if authors_str:
                        authors_str = authors_str.replace(', and ', ' & ').replace(' and ', ' & ')
                        for author in authors_str.split(' & '):
                            author = author.strip()
                            if not author:
                                continue
                            normalized_author = normalize_author_name(author)
                            if normalized_author:
                                key = normalized_author.lower()
                                if key not in seen_authors:
                                    seen_authors.add(key)
                                    authors_list.append(normalized_author)

                tags_list = []
                if row['tags']:
                    seen_tags = set()
                    for tag in row['tags'].split(','):
                        tag = tag.strip()
                        if tag and tag.lower() not in seen_tags:
                            seen_tags.add(tag.lower())
                            tags_list.append(tag)

                book = {
                    'id': row['id'],
                    'title': row['title'],
                    'authors': authors_list,
                    'tags': tags_list,
                    'comments': row['comments'],
                    'publisher': row['publisher'],
                    'series': row['series'],
                    'series_index': row['series_index'],
                    'timestamp': row['timestamp'],
                    'pubdate': row['pubdate'],
                    'has_cover': bool(row['has_cover']),
                    'formats': formats,
                    'path': row['path'],
                }
                books.append(book)

            return books
    except Exception as e:
        print(f"❌ Error loading books: {e}")
        return []


def get_book_cover(book_id):
    """Get the cover image for a book."""
    try:
        cached = cover_cache.get(book_id)

        if cached is None:
            cover_cache.load_all()
            cached = cover_cache.get(book_id)

        if cached is None:
            with get_db_connection(readonly=True) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT path, has_cover FROM books WHERE id = ?", (book_id,))
                row = cursor.fetchone()

                if not row:
                    return None

                cached = {
                    'path': row['path'],
                    'has_cover': bool(row['has_cover']),
                }

        if not cached.get('has_cover'):
            return None

        library_path = get_calibre_library()
        cover_path = os.path.join(library_path, cached['path'], 'cover.jpg')

        if os.path.exists(cover_path):
            with open(cover_path, 'rb') as f:
                return f.read()

        return None
    except Exception as e:
        print(f"❌ Error loading cover for book {book_id}: {e}")
        return None


def get_reading_list_books(sort='added', user='default'):
    """Get books that are on the reading list for a specific user."""
    reading_list_ids = get_reading_list_ids_for_user(user)
    if not reading_list_ids:
        return []

    try:
        with get_db_connection(readonly=True) as conn:
            cursor = conn.cursor()

            placeholders = ','.join('?' * len(reading_list_ids))

            if sort == 'title':
                order_clause = "ORDER BY b.sort"
            elif sort == 'author':
                order_clause = "ORDER BY authors, b.sort"
            else:
                order_clause = "ORDER BY b.timestamp DESC"

            query = f"""
                SELECT
                    b.id,
                    b.title,
                    b.sort,
                    b.timestamp,
                    b.pubdate,
                    b.path,
                    b.has_cover,
                    GROUP_CONCAT(a.name, ' & ') as authors
                FROM books b
                LEFT JOIN books_authors_link bal ON b.id = bal.book
                LEFT JOIN authors a ON bal.author = a.id
                WHERE b.id IN ({placeholders})
                GROUP BY b.id {order_clause}
            """

            cursor.execute(query, reading_list_ids)
            rows = cursor.fetchall()

            book_ids = [row['id'] for row in rows]
            formats_map = {}
            if book_ids:
                fmt_placeholders = ','.join('?' * len(book_ids))
                cursor.execute(
                    f"SELECT book, format, uncompressed_size FROM data WHERE book IN ({fmt_placeholders})",
                    book_ids,
                )
                for fmt_row in cursor.fetchall():
                    book_id = fmt_row['book']
                    if book_id not in formats_map:
                        formats_map[book_id] = []
                    formats_map[book_id].append({
                        'format': fmt_row['format'].upper(),
                        'size': fmt_row['uncompressed_size'] or 0,
                    })

            library_path = get_calibre_library()

            books = []
            for row in rows:
                formats = formats_map.get(row['id'], [])

                format_names = [f['format'] for f in formats]
                if 'KEPUB' not in format_names and row['path']:
                    book_dir = os.path.join(library_path, row['path'])
                    if os.path.isdir(book_dir):
                        for filename in os.listdir(book_dir):
                            if filename.lower().endswith('.kepub'):
                                kepub_path = os.path.join(book_dir, filename)
                                try:
                                    size = os.path.getsize(kepub_path)
                                except Exception:
                                    size = 0
                                formats.append({'format': 'KEPUB', 'size': size})
                                break

                authors_list = []
                seen_authors = set()

                if row['authors']:
                    for author in row['authors'].split(' & '):
                        normalized = normalize_author_name(author.strip())
                        if normalized:
                            key = normalized.lower()
                            if key not in seen_authors:
                                seen_authors.add(key)
                                authors_list.append(normalized)

                book = {
                    'id': row['id'],
                    'title': row['title'],
                    'authors': authors_list if authors_list else ['Unknown Author'],
                    'timestamp': row['timestamp'],
                    'pubdate': row['pubdate'],
                    'has_cover': bool(row['has_cover']),
                    'formats': formats,
                    'path': row['path'],
                }
                books.append(book)

            return books
    except Exception as e:
        print(f"❌ Error loading reading list books: {e}")
        return []


def render_kobo_page(books, page=1, sort='added', books_per_page=5):
    """Render the Kobo e-ink HTML page server-side."""
    total_books = len(books)
    total_pages = max(1, (total_books + books_per_page - 1) // books_per_page)
    page = max(1, min(page, total_pages))

    start_idx = (page - 1) * books_per_page
    end_idx = start_idx + books_per_page
    page_books = books[start_idx:end_idx]

    def format_size(size_bytes):
        if not size_bytes:
            return ''
        if size_bytes >= 1024 * 1024:
            return f"{size_bytes / (1024 * 1024):.1f} MB"
        if size_bytes >= 1024:
            return f"{size_bytes / 1024:.0f} KB"
        return f"{size_bytes} B"

    def format_authors(authors_list):
        if not authors_list:
            return 'Unknown Author'
        return ', '.join(authors_list)

    book_items_html = ''
    for book in page_books:
        authors_str = escape_html(format_authors(book.get('authors', [])))
        title_str = escape_html(book.get('title', 'Unknown Title'))

        formats = book.get('formats', [])
        preferred_format = None
        format_info = ''

        for fmt in formats:
            if fmt['format'] == 'EPUB':
                preferred_format = fmt
                break
        if not preferred_format and formats:
            preferred_format = formats[0]

        if preferred_format:
            size_str = format_size(preferred_format['size'])
            format_info = f"KOBO {preferred_format['format']}"
            if size_str:
                format_info += f" · {size_str}"

        download_url = f"/api/download/{book['id']}/{preferred_format['format']}" if preferred_format else '#'

        book_items_html += f'''
    <li class="book-item">
      <img src="/api/cover/{book['id']}" alt="" class="book-cover">
      <div class="book-info">
        <h2 class="book-title">{title_str}</h2>
        <p class="book-author">{authors_str}</p>
      </div>
      <div class="book-meta">
        <div class="file-info">{format_info}</div>
        <a class="download-btn" href="{download_url}">Download</a>
      </div>
    </li>'''

    sort_options = {
        'added': 'Added',
        'title': 'Title',
        'author': 'Author',
    }
    sort_options_html = ''.join(
        f'<option value="{key}"{" selected" if sort == key else ""}>{label}</option>'
        for key, label in sort_options.items()
    )

    prev_page = page - 1 if page > 1 else 1
    next_page = page + 1 if page < total_pages else total_pages
    prev_disabled = ' disabled' if page <= 1 else ''
    next_disabled = ' disabled' if page >= total_pages else ''

    html = f'''<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Folio - Reading List</title>
  <style>
    body {{
      font-family: sans-serif;
      margin: 0;
      padding: 0;
      background: #f9f9f9;
      color: #000;
    }}
    .header {{
      position: fixed;
      top: 0;
      left: 0;
      right: 0;
      height: 70px;
      display: table;
      width: 100%;
      background: #fff;
      border-bottom: 2px solid #000;
      padding: 0 16px;
      box-sizing: border-box;
    }}
    .header-logo {{
      display: table-cell;
      vertical-align: middle;
    }}
    .header-logo svg {{
      width: 32px;
      height: 32px;
    }}
    .header-title {{
      display: table-cell;
      vertical-align: middle;
      padding-left: 10px;
    }}
    .header h1 {{
      font-size: 26px;
      font-weight: 700;
      margin: 0;
      letter-spacing: -0.5px;
    }}
    .header-sort {{
      display: table-cell;
      vertical-align: middle;
      text-align: right;
    }}
    .sort-form {{
      display: inline;
    }}
    .sort-select {{
      background: #fff;
      border: 2px solid #000;
      padding: 12px 16px;
      font-size: 18px;
      font-weight: 500;
      min-width: 140px;
    }}
    .content {{
      position: absolute;
      top: 70px;
      bottom: 80px;
      left: 0;
      right: 0;
      overflow: hidden;
    }}
    .book-list {{
      list-style: none;
      margin: 0;
      padding: 0;
    }}
    .book-item {{
      display: table;
      width: 100%;
      padding: 14px 16px;
      border-bottom: 1px solid #ccc;
    }}
    .book-cover {{
      display: table-cell;
      vertical-align: top;
      width: 70px;
      height: 100px;
      background: #ddd;
      border: 1px solid #999;
    }}
    .book-cover img {{
      width: 70px;
      height: 100px;
      object-fit: cover;
    }}
    .book-info {{
      display: table-cell;
      vertical-align: top;
      padding: 0 16px;
    }}
    .book-title {{
      font-size: 22px;
      font-weight: 600;
      margin: 0 0 6px 0;
      line-height: 1.25;
    }}
    .book-author {{
      font-size: 18px;
      color: #333;
      margin: 0;
    }}
    .book-meta {{
      display: table-cell;
      vertical-align: middle;
      text-align: right;
      white-space: nowrap;
      width: 130px;
    }}
    .file-info {{
      font-size: 14px;
      color: #555;
      margin-bottom: 10px;
    }}
    .download-btn {{
      display: inline-block;
      background: #000;
      color: #fff;
      border: none;
      padding: 14px 20px;
      font-size: 18px;
      font-weight: 600;
      text-decoration: none;
      text-align: center;
    }}
    .empty-state {{
      padding: 50px 24px;
      text-align: center;
      color: #555;
    }}
    .empty-state p {{
      margin: 12px 0;
      font-size: 20px;
    }}
    .pagination {{
      position: fixed;
      bottom: 0;
      left: 0;
      right: 0;
      background: #f0f0f0;
      border-top: 2px solid #000;
      padding: 12px 16px;
      display: table;
      width: 100%;
    }}
    .pagination-left {{
      display: table-cell;
      text-align: left;
      width: 33%;
    }}
    .pagination-center {{
      display: table-cell;
      text-align: center;
      width: 34%;
      font-size: 18px;
      color: #333;
      vertical-align: middle;
    }}
    .pagination-right {{
      display: table-cell;
      text-align: right;
      width: 33%;
    }}
    .nav-btn {{
      display: inline-block;
      background: #000;
      color: #fff;
      border: 2px solid #000;
      padding: 16px 28px;
      font-size: 20px;
      font-weight: 600;
      text-decoration: none;
      text-align: center;
      min-width: 120px;
    }}
    .nav-btn[disabled],
    .nav-btn.disabled {{
      background: #ccc;
      color: #888;
      border-color: #999;
      pointer-events: none;
    }}
    .page-info {{
      font-weight: 500;
    }}
  </style>
</head>
<body>
  <div class="header">
    <div class="header-logo">
      <svg viewBox="0 0 100 100" fill="none" xmlns="http://www.w3.org/2000/svg">
        <rect width="100" height="100" rx="20" fill="#000"/>
        <path d="M25 20h50v60H25z" fill="#fff"/>
        <path d="M30 25h40v50H30z" fill="#000"/>
        <path d="M35 35h25v3H35zM35 42h30v2H35zM35 48h28v2H35zM35 54h30v2H35zM35 60h20v2H35z" fill="#fff"/>
      </svg>
    </div>
    <div class="header-title">
      <h1>Reading List</h1>
    </div>
    <div class="header-sort">
      <form method="GET" action="/kobo" class="sort-form">
        <input type="hidden" name="page" value="1">
        <select name="sort" class="sort-select" onchange="this.form.submit()">
          {sort_options_html}
        </select>
        <noscript><button type="submit" class="nav-btn" style="margin-left:8px;padding:10px 16px;">Go</button></noscript>
      </form>
    </div>
  </div>
  
  <div class="content">
    <ul class="book-list">
{book_items_html}
    </ul>
  </div>
  
  <div class="pagination">
    <div class="pagination-left">
      <a href="/kobo?page={prev_page}&amp;sort={sort}" class="nav-btn{prev_disabled}">← Prev</a>
    </div>
    <div class="pagination-center">
      <span class="page-info">{page} / {total_pages}</span>
    </div>
    <div class="pagination-right">
      <a href="/kobo?page={next_page}&amp;sort={sort}" class="nav-btn{next_disabled}">Next →</a>
    </div>
  </div>
</body>
</html>'''

    return html

