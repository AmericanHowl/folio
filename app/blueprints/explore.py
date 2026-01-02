from flask import Blueprint, render_template

explore_bp = Blueprint('explore', __name__, url_prefix='/explore')


@explore_bp.route('/')
def index():
    """Explore page - browse and discover new books."""
    # TODO: Implement Hardcover API integration in Phase 2
    return render_template('explore/index.html')
