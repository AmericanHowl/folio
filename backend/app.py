"""
Folio Backend - Calibre Metadata Management API
Handles metadata updates and cover art uploads for Calibre library
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
import subprocess
import os
import base64
import tempfile
from pathlib import Path

app = Flask(__name__)
CORS(app)  # Enable CORS for frontend access

# Calibre library path (should be mounted in Docker)
CALIBRE_LIBRARY = os.getenv('CALIBRE_LIBRARY', '/calibre-library')


def run_calibredb(args):
    """
    Execute calibredb command with the library path
    """
    cmd = ['calibredb'] + args + ['--library-path', CALIBRE_LIBRARY]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True
        )
        return {'success': True, 'output': result.stdout}
    except subprocess.CalledProcessError as e:
        return {'success': False, 'error': e.stderr}


@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({'status': 'healthy', 'library': CALIBRE_LIBRARY})


@app.route('/api/metadata/<int:book_id>', methods=['PUT'])
def update_metadata(book_id):
    """
    Update book metadata
    Expected JSON body:
    {
        "title": "Book Title",
        "authors": "Author 1, Author 2",
        "publisher": "Publisher Name",
        "comments": "Book description"
    }
    """
    data = request.json

    if not data:
        return jsonify({'error': 'No data provided'}), 400

    # Update title
    if 'title' in data:
        result = run_calibredb(['set_metadata', str(book_id), '--field', f'title:{data["title"]}'])
        if not result['success']:
            return jsonify({'error': f'Failed to update title: {result["error"]}'}), 500

    # Update authors
    if 'authors' in data:
        # Handle both string and array formats
        authors = data['authors']
        if isinstance(authors, list):
            authors = ', '.join(authors)

        result = run_calibredb(['set_metadata', str(book_id), '--field', f'authors:{authors}'])
        if not result['success']:
            return jsonify({'error': f'Failed to update authors: {result["error"]}'}), 500

    # Update publisher
    if 'publisher' in data:
        result = run_calibredb(['set_metadata', str(book_id), '--field', f'publisher:{data["publisher"]}'])
        if not result['success']:
            return jsonify({'error': f'Failed to update publisher: {result["error"]}'}), 500

    # Update description/comments
    if 'comments' in data:
        result = run_calibredb(['set_metadata', str(book_id), '--field', f'comments:{data["comments"]}'])
        if not result['success']:
            return jsonify({'error': f'Failed to update comments: {result["error"]}'}), 500

    return jsonify({'success': True, 'message': 'Metadata updated successfully'})


@app.route('/api/cover/<int:book_id>', methods=['PUT'])
def update_cover(book_id):
    """
    Update book cover art
    Expected JSON body:
    {
        "coverData": "data:image/jpeg;base64,..."
    }
    """
    data = request.json

    if not data or 'coverData' not in data:
        return jsonify({'error': 'No cover data provided'}), 400

    # Parse base64 data URL
    cover_data = data['coverData']
    if not cover_data.startswith('data:image'):
        return jsonify({'error': 'Invalid cover data format'}), 400

    # Extract base64 content
    try:
        header, encoded = cover_data.split(',', 1)
        image_data = base64.b64decode(encoded)

        # Determine file extension from MIME type
        mime_type = header.split(';')[0].split(':')[1]
        ext_map = {
            'image/jpeg': '.jpg',
            'image/jpg': '.jpg',
            'image/png': '.png',
            'image/gif': '.gif'
        }
        ext = ext_map.get(mime_type, '.jpg')

        # Save to temporary file
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp_file:
            tmp_file.write(image_data)
            tmp_path = tmp_file.name

        # Update cover using calibredb
        result = run_calibredb(['set_metadata', str(book_id), '--cover', tmp_path])

        # Clean up temp file
        os.unlink(tmp_path)

        if not result['success']:
            return jsonify({'error': f'Failed to update cover: {result["error"]}'}), 500

        return jsonify({'success': True, 'message': 'Cover updated successfully'})

    except Exception as e:
        return jsonify({'error': f'Failed to process cover image: {str(e)}'}), 500


@app.route('/api/metadata-and-cover/<int:book_id>', methods=['PUT'])
def update_metadata_and_cover(book_id):
    """
    Update both metadata and cover in a single request
    Combines both endpoints for efficiency
    """
    data = request.json

    if not data:
        return jsonify({'error': 'No data provided'}), 400

    errors = []

    # Update metadata fields
    metadata_fields = ['title', 'authors', 'publisher', 'comments']
    for field in metadata_fields:
        if field in data:
            value = data[field]
            if isinstance(value, list):
                value = ', '.join(value)

            result = run_calibredb(['set_metadata', str(book_id), '--field', f'{field}:{value}'])
            if not result['success']:
                errors.append(f'Failed to update {field}: {result["error"]}')

    # Update cover if provided
    if 'coverData' in data and data['coverData']:
        try:
            cover_data = data['coverData']
            header, encoded = cover_data.split(',', 1)
            image_data = base64.b64decode(encoded)

            mime_type = header.split(';')[0].split(':')[1]
            ext_map = {'image/jpeg': '.jpg', 'image/jpg': '.jpg', 'image/png': '.png', 'image/gif': '.gif'}
            ext = ext_map.get(mime_type, '.jpg')

            with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp_file:
                tmp_file.write(image_data)
                tmp_path = tmp_file.name

            result = run_calibredb(['set_metadata', str(book_id), '--cover', tmp_path])
            os.unlink(tmp_path)

            if not result['success']:
                errors.append(f'Failed to update cover: {result["error"]}')
        except Exception as e:
            errors.append(f'Failed to process cover: {str(e)}')

    if errors:
        return jsonify({'success': False, 'errors': errors}), 500

    return jsonify({'success': True, 'message': 'Metadata and cover updated successfully'})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
