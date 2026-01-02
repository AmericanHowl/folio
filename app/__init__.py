import os
from flask import Flask, redirect, url_for
from app.config import config
from app.models import db
from app.models.settings import Setting


def create_app(config_name=None):
    """Application factory pattern."""
    if config_name is None:
        config_name = os.environ.get('FLASK_ENV', 'development')

    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config[config_name])

    # Initialize extensions
    db.init_app(app)

    # Create database tables
    with app.app_context():
        db.create_all()

    # Register blueprints
    from app.blueprints.setup import setup_bp
    from app.blueprints.library import library_bp
    from app.blueprints.requests import requests_bp
    from app.blueprints.explore import explore_bp

    app.register_blueprint(setup_bp)
    app.register_blueprint(library_bp)
    app.register_blueprint(requests_bp)
    app.register_blueprint(explore_bp)

    # Root route - redirect based on setup status
    @app.route('/')
    def index():
        if not Setting.is_configured():
            return redirect(url_for('setup.initial_setup'))
        return redirect(url_for('library.index'))

    # Template context processors
    @app.context_processor
    def inject_globals():
        return {
            'app_name': app.config['APP_NAME'],
            'app_version': app.config['APP_VERSION'],
        }

    return app
