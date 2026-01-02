from flask import Blueprint, render_template, request, jsonify, send_file
from app.services.calibre import CalibreService
from app.models.settings import Setting
import tempfile
import os

library_bp = Blueprint('library', __name__, url_prefix='/library')


@library_bp.route('/')
def index():
    """Library main page - browse and download books."""
    page = request.args.get('page', 1, type=int)
    per_page = 20
    search_query = request.args.get('q', '').strip()

    try:
        calibre = CalibreService()

        if search_query:
            books = calibre.search_books(search_query)
        else:
            offset = (page - 1) * per_page
            books = calibre.list_books(limit=per_page, offset=offset)

        total_books = calibre.get_book_count()
        total_pages = (total_books + per_page - 1) // per_page

        return render_template('library/index.html',
                               books=books,
                               page=page,
                               total_pages=total_pages,
                               total_books=total_books,
                               search_query=search_query)

    except ValueError as e:
        # Not configured yet
        return render_template('library/not_configured.html', error=str(e))
    except Exception as e:
        return render_template('library/error.html', error=str(e)), 500


@library_bp.route('/book/<int:book_id>')
def book_detail(book_id):
    """Book detail page with metadata and download options."""
    try:
        calibre = CalibreService()
        book = calibre.get_book(book_id)

        if not book:
            return render_template('library/error.html',
                                   error=f'Book with ID {book_id} not found'), 404

        return render_template('library/detail.html', book=book)

    except Exception as e:
        return render_template('library/error.html', error=str(e)), 500


@library_bp.route('/download/<int:book_id>')
def download_book(book_id):
    """Download a book file."""
    try:
        calibre = CalibreService()
        book = calibre.get_book(book_id)

        if not book:
            return jsonify({'error': 'Book not found'}), 404

        # Create temporary directory for export
        with tempfile.TemporaryDirectory() as temp_dir:
            calibre.export_book(book_id, temp_dir)

            # Find the exported file
            files = os.listdir(temp_dir)
            if not files:
                return jsonify({'error': 'Export failed - no files generated'}), 500

            # Return the first file found
            file_path = os.path.join(temp_dir, files[0])
            return send_file(file_path, as_attachment=True)

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@library_bp.route('/api/books')
def api_books():
    """API endpoint for book listing (HTMX)."""
    page = request.args.get('page', 1, type=int)
    per_page = 20
    search_query = request.args.get('q', '').strip()

    try:
        calibre = CalibreService()

        if search_query:
            books = calibre.search_books(search_query)
        else:
            offset = (page - 1) * per_page
            books = calibre.list_books(limit=per_page, offset=offset)

        return render_template('library/partials/book_grid.html', books=books)

    except Exception as e:
        return jsonify({'error': str(e)}), 500
