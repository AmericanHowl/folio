"""
ORPHANED MODULE - This file is not used. See folio_app/__init__.py for details.
Duplicate of configuration code in folio.py which is actually used.

Original description:
Configuration management for Folio.
Handles loading, saving, and accessing configuration values.
"""
import os
import json
import threading

# Configuration file paths
CONFIG_FILE = "config.json"
IMPORTED_FILES_FILE = "imported_files.json"
FOLIO_DB_FILE = "folio.db"

# Server settings
PORT = 9099

# External API URLs
HARDCOVER_API_URL = "https://api.hardcover.app/v1/graphql"
KOBO_STOREAPI_URL = "https://storeapi.kobo.com"

# Cache TTL values (in seconds)
CACHE_TTL_HARDCOVER_TRENDING = 300  # 5 minutes
CACHE_TTL_HARDCOVER_RECENT = 300    # 5 minutes
CACHE_TTL_HARDCOVER_LISTS = 600     # 10 minutes
CACHE_TTL_HARDCOVER_LIST = 600      # 10 minutes
CACHE_TTL_HARDCOVER_AUTHOR = 600    # 10 minutes
CACHE_TTL_ITUNES_SEARCH = 1800      # 30 minutes

# Global configuration dictionary
config = {
    'calibre_library': os.getenv('CALIBRE_LIBRARY', os.path.expanduser('~/Calibre Library')),
    'calibredb_path': os.getenv('CALIBREDB_PATH', ''),
    'hardcover_token': os.getenv('HARDCOVER_TOKEN', ''),
    'prowlarr_url': os.getenv('PROWLARR_URL', ''),
    'prowlarr_api_key': os.getenv('PROWLARR_API_KEY', ''),
    'requested_books': [],
    'import_folder': os.getenv('IMPORT_FOLDER', ''),
    'import_interval': int(os.getenv('IMPORT_INTERVAL', '60')),
    'import_recursive': os.getenv('IMPORT_RECURSIVE', 'true').lower() == 'true',
    'import_delete': os.getenv('IMPORT_DELETE', 'true').lower() == 'true',
}

# Import watcher state
import_state = {
    'running': False,
    'last_scan': None,
    'last_import': None,
    'imported_files': [],
    'last_imported_count': 0,
    'total_imported': 0,
    'errors': [],
    'kepub_converting': None,
    'kepub_convert_start': None,
    'kepub_last_file': None,
    'kepub_last_success': None,
    'kepub_last_log': None,
}

# Thread lock for import state
import_state_lock = threading.Lock()

# Track watcher thread
_import_watcher_thread = None


def sanitize_token(token):
    """Sanitize API token by removing whitespace, newlines, and 'Bearer ' prefix."""
    if not token:
        return ''
    token = token.strip()
    if token.startswith('Bearer '):
        token = token[7:]
    return token.strip()


def load_config():
    """Load configuration from file, merging with environment variables.

    Environment variables take precedence over file values when set.
    """
    global config

    env_config = {
        'calibre_library': os.getenv('CALIBRE_LIBRARY', ''),
        'calibredb_path': os.getenv('CALIBREDB_PATH', ''),
        'hardcover_token': sanitize_token(os.getenv('HARDCOVER_TOKEN', '')),
        'prowlarr_url': os.getenv('PROWLARR_URL', '').strip(),
        'prowlarr_api_key': sanitize_token(os.getenv('PROWLARR_API_KEY', '')),
    }

    file_config = {}
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                file_config = json.load(f)
        except Exception as e:
            print(f"⚠️  Failed to load config: {e}")

    config.update(file_config)

    for key, value in env_config.items():
        if value:
            config[key] = value

    config.setdefault('calibre_library', os.path.expanduser('~/Calibre Library'))
    config.setdefault('calibredb_path', '')
    config.setdefault('hardcover_token', '')
    config.setdefault('prowlarr_url', '')
    config.setdefault('prowlarr_api_key', '')
    config.setdefault('requested_books', [])

    return config


def save_config():
    """Save configuration to file."""
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=2)
        return True
    except Exception as e:
        print(f"⚠️  Failed to save config: {e}")
        return False


def get_calibre_library():
    """Get the current Calibre library path."""
    return config.get('calibre_library', os.path.expanduser('~/Calibre Library'))


def get_folio_db_path():
    """Get path to folio.db in the calibre library directory."""
    library_path = get_calibre_library()
    return os.path.join(library_path, FOLIO_DB_FILE)


def load_imported_files():
    """Load list of already-imported files from disk."""
    global import_state
    if os.path.exists(IMPORTED_FILES_FILE):
        try:
            with open(IMPORTED_FILES_FILE, 'r') as f:
                data = json.load(f)
                with import_state_lock:
                    import_state['imported_files'] = data.get('files', [])
                print(f"📂 Loaded {len(import_state['imported_files'])} previously imported files")
        except Exception as e:
            print(f"⚠️  Failed to load imported files list: {e}")
            with import_state_lock:
                import_state['imported_files'] = []
    else:
        with import_state_lock:
            import_state['imported_files'] = []


def save_imported_files():
    """Save list of imported files to disk for persistence."""
    try:
        with import_state_lock:
            files_to_save = list(import_state.get('imported_files', []))

        temp_file = IMPORTED_FILES_FILE + '.tmp'
        with open(temp_file, 'w') as f:
            json.dump({'files': files_to_save}, f, indent=2)
            f.flush()
            os.fsync(f.fileno())

        os.replace(temp_file, IMPORTED_FILES_FILE)
        return True
    except Exception as e:
        print(f"⚠️  Failed to save imported files list: {e}")
        try:
            if os.path.exists(temp_file):
                os.remove(temp_file)
        except Exception:
            pass
        return False
