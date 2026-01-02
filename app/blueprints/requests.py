from flask import Blueprint, render_template

requests_bp = Blueprint('requests', __name__, url_prefix='/requests')


@requests_bp.route('/')
def index():
    """Requests page - shared queue for book requests."""
    # TODO: Implement requests functionality in Phase 2
    return render_template('requests/index.html')
