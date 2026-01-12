"""
Database modules for Folio.
Handles connections to both Calibre's metadata.db and Folio's folio.db.
"""
from .connection import get_folio_db_connection, get_calibre_db_connection
from .folio import init_folio_db
