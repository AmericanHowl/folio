# Folio Backend

Python Flask backend for handling Calibre metadata updates.

## Features

- Update book metadata (title, authors, publisher, description)
- Upload and update cover art
- Uses `calibredb` CLI for all operations
- CORS enabled for frontend access

## API Endpoints

### Health Check
```
GET /health
```

### Update Metadata
```
PUT /api/metadata/<book_id>
Content-Type: application/json

{
  "title": "New Title",
  "authors": "Author 1, Author 2",
  "publisher": "Publisher Name",
  "comments": "Book description"
}
```

### Update Cover
```
PUT /api/cover/<book_id>
Content-Type: application/json

{
  "coverData": "data:image/jpeg;base64,..."
}
```

### Update Both
```
PUT /api/metadata-and-cover/<book_id>
Content-Type: application/json

{
  "title": "New Title",
  "authors": "Author 1, Author 2",
  "publisher": "Publisher Name",
  "comments": "Book description",
  "coverData": "data:image/jpeg;base64,..."
}
```

## Environment Variables

- `CALIBRE_LIBRARY`: Path to Calibre library (default: `/calibre-library`)

## Development

```bash
# Install dependencies
pip install -r requirements.txt

# Run the server
python app.py
```

## Docker

The backend is automatically built and run via docker-compose.yml
