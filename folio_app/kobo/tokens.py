"""
Kobo sync token management.
"""
import uuid

from ..database.connection import get_folio_db_connection


def generate_kobo_token():
    """Generate a new unique Kobo sync token (UUID4)."""
    return str(uuid.uuid4())


def get_kobo_token_for_user(user):
    """Get the Kobo sync token for a user, creating one if it doesn't exist."""
    try:
        with get_folio_db_connection(readonly=True) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT auth_token FROM kobo_tokens WHERE user = ?", (user,))
            row = cursor.fetchone()

            if row:
                return row['auth_token']

        # No token exists, create one
        token = generate_kobo_token()
        with get_folio_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO kobo_tokens (user, auth_token) VALUES (?, ?)",
                (user, token)
            )
            conn.commit()
        print(f"🔑 Created new Kobo sync token for user '{user}'")
        return token
    except Exception as e:
        print(f"❌ Failed to get/create Kobo token for user {user}: {e}")
        return None


def get_user_from_kobo_token(token):
    """Get the user associated with a Kobo sync token."""
    try:
        with get_folio_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT user FROM kobo_tokens WHERE auth_token = ?", (token,))
            row = cursor.fetchone()

            if row:
                cursor.execute(
                    "UPDATE kobo_tokens SET last_used = CURRENT_TIMESTAMP WHERE auth_token = ?",
                    (token,)
                )
                conn.commit()
                return row['user']

            return None
    except Exception as e:
        print(f"❌ Failed to validate Kobo token: {e}")
        return None


def regenerate_kobo_token_for_user(user):
    """Regenerate the Kobo sync token for a user."""
    try:
        token = generate_kobo_token()
        with get_folio_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR REPLACE INTO kobo_tokens (user, auth_token, created_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
                (user, token)
            )
            conn.commit()
        print(f"🔑 Regenerated Kobo sync token for user '{user}'")
        return token
    except Exception as e:
        print(f"❌ Failed to regenerate Kobo token for user {user}: {e}")
        return None
