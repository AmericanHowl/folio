#!/usr/bin/env python3
"""Run the Folio application."""
import os
from app import create_app

if __name__ == '__main__':
    app = create_app()

    # Get configuration from environment
    host = os.environ.get('FLASK_HOST', '0.0.0.0')
    port = int(os.environ.get('FLASK_PORT', 9099))
    debug = os.environ.get('FLASK_ENV', 'development') == 'development'

    app.run(host=host, port=port, debug=debug)
