"""
Server startup for Folio.
Keeps the entrypoint logic separate from core handlers.
"""
import importlib
import sys
import threading
import socketserver
from socketserver import ThreadingMixIn


def _resolve_core_module():
    """Prefer the running __main__ module to avoid double imports."""
    main_mod = sys.modules.get("__main__")
    if main_mod and getattr(main_mod, "__file__", "").endswith("folio.py"):
        return main_mod
    return importlib.import_module("folio")


def main():
    core = _resolve_core_module()

    # Load config on startup
    core.load_config()

    # Initialize folio database for multi-user reading lists
    core.init_folio_db()

    # Migrate import history from JSON to database (one-time migration)
    core.migrate_import_history_from_json()

    # Pre-load cover cache asynchronously (don't block server startup)
    def preload_cover_cache():
        print("📦 Pre-loading cover cache in background...")
        core.cover_cache.load_all()

    cache_thread = threading.Thread(target=preload_cover_cache, daemon=True)
    cache_thread.start()

    # Start import watcher if configured
    core.start_import_watcher()

    # Use threaded server to handle concurrent cover image requests
    class ThreadedTCPServer(ThreadingMixIn, socketserver.TCPServer):
        allow_reuse_address = True
        daemon_threads = True  # Threads die when main thread exits

    with ThreadedTCPServer(("", core.PORT), core.FolioHandler) as httpd:
        print(f"🚀 Folio server running at http://localhost:{core.PORT}")
        print(f"📖 Calibre Library: {core.get_calibre_library()}")
        print(f"🔑 Hardcover API: {'Configured' if core.config.get('hardcover_token') else 'Not configured'}")
        print(
            f"🔍 Prowlarr: "
            f"{'Configured (' + core.config.get('prowlarr_url', '') + ')' if core.config.get('prowlarr_url') and core.config.get('prowlarr_api_key') else 'Not configured'}"
        )
        import_folder = core.config.get('import_folder', '')
        if import_folder:
            print(
                f"📂 Import Folder: {import_folder} "
                f"(interval: {core.config.get('import_interval', 60)}s, "
                f"recursive: {core.config.get('import_recursive', True)}, "
                f"delete: {core.config.get('import_delete', False)})"
            )
        else:
            print("📂 Import Folder: Not configured")
        print("\n   Library APIs:")
        print("   /api/books → Book list from metadata.db")
        print("   /api/cover/* → Book covers")
        print("   /api/download/{id}/{format} → Download book files")
        print("   /api/metadata-and-cover/* → Metadata editing")
        print("\n   Hardcover APIs:")
        print("   /api/itunes/search?q=query → Search iTunes (for metadata)")
        print("   /api/hardcover/trending → Most popular books from 2025")
        print("\n   Lists:")
        print("   /api/requests → Manage book requests")
        print("   /api/reading-list → Manage reading list (library books)")
        print("\n   Config:")
        print("   /api/config → Configuration")
        print("   /api/browse → Directory browser")
        print("\n   Import:")
        print("   /api/import/status → Import watcher status")
        print("   /api/import/scan → Trigger manual import (POST)")
        print("\n   Kobo Sync:")
        print("   /api/kobo/token → Get/create sync token")
        print("   /kobo/<token>/v1/library/sync → Sync reading list to Kobo")
        print(f"\n   📱 E-ink interface: http://localhost:{core.PORT}/eink.html")
        print(f"   📖 Kobo interface: http://localhost:{core.PORT}/kobo")
        print("   📲 Kobo Sync: Configure in Settings → Kobo Sync")
        print("\nPress Ctrl+C to stop")
        httpd.serve_forever()

