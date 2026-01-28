"""
Reading list helpers for multi-user support.
"""
from .database.connection import get_folio_db_connection


def get_user_from_headers(headers):
    """
    Extract username from Cloudflare Access or proxy headers.
    Returns 'default' if no user header is found (backward compatible).
    """
    cf_email = headers.get('Cf-Access-Authenticated-User-Email')
    if cf_email:
        return cf_email.strip().lower()

    fallback_headers = [
        'X-authentik-username',
        'Remote-User',
        'X-Forwarded-User',
        'X-Auth-Request-User',
    ]

    for header in fallback_headers:
        user = headers.get(header)
        if user:
            return user.strip().lower()

    return 'default'


def get_reading_list_ids_for_user(user='default'):
    """Get IDs of books on the reading list for a specific user."""
    try:
        conn = get_folio_db_connection(readonly=True)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT book_id FROM reading_list WHERE user = ? ORDER BY added_at DESC",
            (user,),
        )
        rows = cursor.fetchall()
        conn.close()
        return [row['book_id'] for row in rows]
    except Exception as e:
        print(f"⚠️ Failed to get reading list for user {user}: {e}")
        return []


def add_to_reading_list_for_user(book_id, user='default'):
    """Add a book to the reading list for a specific user."""
    try:
        conn = get_folio_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR IGNORE INTO reading_list (user, book_id) VALUES (?, ?)",
            (user, book_id),
        )
        conn.commit()
        conn.close()
        print(f"✅ Added book {book_id} to reading list for user '{user}'")
        return True
    except Exception as e:
        print(f"❌ Failed to add book {book_id} to reading list for user {user}: {e}")
        return False


def remove_from_reading_list_for_user(book_id, user='default'):
    """Remove a book from the reading list for a specific user."""
    try:
        conn = get_folio_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM reading_list WHERE user = ? AND book_id = ?",
            (user, book_id),
        )
        conn.commit()
        conn.close()
        print(f"✅ Removed book {book_id} from reading list for user '{user}'")
        return True
    except Exception as e:
        print(f"❌ Failed to remove book {book_id} from reading list for user {user}: {e}")
        return False

