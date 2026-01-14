"""
ORPHANED MODULE - This file is not used. See folio_app/__init__.py for details.
Duplicate of text utility functions in folio.py which are actually used.
"""
import html


def sanitize_token(token):
    """Sanitize API token by removing whitespace, newlines, and 'Bearer ' prefix."""
    if not token:
        return ''
    token = token.strip()
    if token.startswith('Bearer '):
        token = token[7:]
    return token.strip()


def escape_html(text):
    """Escape HTML special characters."""
    if text is None:
        return ''
    return html.escape(str(text))


def safe_filename(filename):
    """Create a safe filename by removing/replacing problematic characters."""
    if not filename:
        return 'unknown'
    # Replace problematic characters
    for char in ['/', '\\', ':', '*', '?', '"', '<', '>', '|']:
        filename = filename.replace(char, '_')
    return filename.strip()
