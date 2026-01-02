from flask import Blueprint, render_template, request, redirect, url_for, flash
from app.models.settings import Setting
from app.services.calibre import CalibreService
import os

setup_bp = Blueprint('setup', __name__, url_prefix='/setup')


@setup_bp.route('/')
def initial_setup():
    """Initial setup page for first-time configuration."""
    return render_template('setup/initial.html')


@setup_bp.route('/configure', methods=['POST'])
def configure():
    """Save initial configuration."""
    calibre_library_path = request.form.get('calibre_library_path', '').strip()
    calibredb_path = request.form.get('calibredb_path', '').strip()

    # Validation
    errors = []

    if not calibre_library_path:
        errors.append('Calibre library path is required')
    elif not os.path.isdir(calibre_library_path):
        errors.append(f'Calibre library path does not exist: {calibre_library_path}')

    if not calibredb_path:
        errors.append('calibredb path is required')
    elif not os.path.isfile(calibredb_path):
        errors.append(f'calibredb executable not found: {calibredb_path}')

    if errors:
        for error in errors:
            flash(error, 'error')
        return render_template('setup/initial.html',
                               calibre_library_path=calibre_library_path,
                               calibredb_path=calibredb_path)

    # Save settings
    Setting.set('calibre_library_path', calibre_library_path,
                'Path to Calibre library directory')
    Setting.set('calibredb_path', calibredb_path,
                'Path to calibredb executable')

    # Verify the configuration works
    try:
        calibre = CalibreService()
        verification = calibre.verify_installation()

        if not all(verification.values()):
            flash('Configuration saved, but verification failed. Please check your paths.', 'warning')
        else:
            flash('Configuration saved successfully!', 'success')

    except Exception as e:
        flash(f'Configuration saved, but verification failed: {str(e)}', 'warning')

    return redirect(url_for('library.index'))


@setup_bp.route('/settings')
def settings():
    """Settings page for reconfiguration."""
    calibre_library_path = Setting.get('calibre_library_path', '')
    calibredb_path = Setting.get('calibredb_path', '')

    return render_template('setup/settings.html',
                           calibre_library_path=calibre_library_path,
                           calibredb_path=calibredb_path)
