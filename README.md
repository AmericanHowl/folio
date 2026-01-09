# Folio

A modern, mobile-first ebook management interface for Calibre libraries with Hardcover.app integration for book discovery.

**Folio** is a clean web app to browse your Calibre library, discover new books via Hardcover.app, and manage a wish list. Built with pure HTML/JS and a single Python script - no complex backend, no Docker required.

## Features

### Library Management
- **Browse your Calibre library** with a modern, card-based interface
- **Dual view modes** - Grid view or horizontal scrolling sections
- **Real-time search** - Find books instantly
- **Smart sorting** - By title, author, date added
- **Genre filtering** - Browse by genre with interactive pills
- **Edit metadata** - Update titles, authors, publisher, descriptions, and cover art

### Book Discovery (Hardcover.app Integration)
- **Search Hardcover** - Discover millions of books
- **Fuzzy matching** - Automatically identifies books you already own
- **Status badges** - See at a glance: "In Library", "Requested", or "Available"
- **Book requests** - Build a wish list of books you want
- **Rich metadata** - View ratings, descriptions, genres, and more
- **Prowlarr integration** - Search for books via Prowlarr (optional)

### Design
- **Warm library theme** - Burnt orange, deep purple, and burgundy color palette
- **Mobile-first** - Optimized for phones and tablets
- **PWA support** - Install as an app on your device
- **E-ink mode** - Dedicated interface for e-readers (Kobo, etc.)

## Quick Start

### Prerequisites

1. **Python 3.7+** (standard library only, no pip installs needed!)
2. **Calibre** installed (optional, for metadata editing via `calibredb`)

### Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/folio.git
cd folio

# Run the server
python3 serve.py
```

Open your browser to `http://localhost:9099`

That's it!

### First-Time Setup

1. On first launch, you'll be prompted to configure:
   - **Hardcover API Key** - Required for book discovery (get from [hardcover.app/account/api](https://hardcover.app/account/api))
   - **Calibre Library** - Browse to the folder containing your `metadata.db` file
   - **Prowlarr** (Optional) - Configure Prowlarr URL and API key for book searching
2. All settings can be updated later from the Settings menu (gear icon in footer)
   - Settings UI allows you to update Hardcover API key, Prowlarr URL, and Prowlarr API key
   - Calibre Library path can be changed from Settings as well

### Getting API Keys

**Hardcover API Token:**
1. Create an account at [hardcover.app](https://hardcover.app)
2. Go to [hardcover.app/account/api](https://hardcover.app/account/api)
3. Copy your API token
4. Paste it in Folio Settings > Hardcover API Key

**Prowlarr API Key (Optional):**
1. Open your Prowlarr instance
2. Go to Settings → General → API Key
3. Copy the API key
4. Enter your Prowlarr URL and API key in Folio Settings > Prowlarr

## Project Structure

```
folio/
├── serve.py              # Python server (static files + APIs)
├── config.json           # Configuration (auto-generated)
├── docker-compose.yml    # Docker Compose configuration
├── public/               # Frontend files
│   ├── index.html        # Main app (warm theme)
│   ├── eink.html         # E-ink device interface
│   ├── manifest.json     # PWA manifest
│   ├── service-worker.js # Offline support
│   ├── js/
│   │   └── app.js        # Alpine.js application
│   └── icons/            # PWA icons
└── README.md
```

## How It Works

### Backend (serve.py)

A single Python script that:
- Serves static files from `public/`
- Reads directly from Calibre's `metadata.db` SQLite database
- Proxies requests to Hardcover's GraphQL API
- Manages book requests (stored in `config.json`)
- Handles metadata updates via `calibredb` CLI

### Frontend

Pure HTML/JS with:
- [Alpine.js](https://alpinejs.dev/) - Reactive UI (15KB)
- [Tailwind CSS](https://tailwindcss.com/) - Styling (CDN)
- [Bootstrap Icons](https://icons.getbootstrap.com/) - Icons
- [Cal Sans + Inter](https://fonts.google.com/) - Typography

### API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/books` | GET | List books from Calibre library |
| `/api/cover/{id}` | GET | Get book cover image |
| `/api/download/{id}/{format}` | GET | Download book file |
| `/api/metadata-and-cover/{id}` | PUT | Update book metadata |
| `/api/hardcover/search?q=` | GET | Search Hardcover.app |
| `/api/hardcover/trending` | GET | Get trending books |
| `/api/hardcover/recent` | GET | Get recent releases |
| `/api/hardcover/lists` | GET | Get popular lists |
| `/api/hardcover/list?id=` | GET | Get books from a list |
| `/api/prowlarr/search?q=` | GET | Search Prowlarr for books |
| `/api/requests` | GET/POST | Manage book requests |
| `/api/requests/{id}` | DELETE | Cancel a book request |
| `/api/reading-list` | GET/POST/DELETE | Manage reading list |
| `/api/config` | GET/POST | App configuration |
| `/api/browse` | GET | Directory browser |

## Configuration

### Environment Variables

```bash
# Set Calibre library path
export CALIBRE_LIBRARY="/path/to/your/Calibre Library"

# Set calibredb path (optional - auto-detected if not set)
export CALIBREDB_PATH="/path/to/calibredb"

# Set Hardcover API token (alternative to Settings UI)
export HARDCOVER_TOKEN="your-api-token"

# Set Prowlarr configuration (optional)
export PROWLARR_URL="http://localhost:9696"
export PROWLARR_API_KEY="your-prowlarr-api-key"

# Run the server
python3 serve.py
```

### config.json

Configuration is stored in `config.json` (auto-generated):

```json
{
  "calibre_library": "/path/to/Calibre Library",
  "calibredb_path": "/path/to/calibredb",
  "hardcover_token": "your-api-token",
  "prowlarr_url": "http://localhost:9696",
  "prowlarr_api_key": "your-prowlarr-api-key",
  "requested_books": []
}
```

All settings can be configured via the Settings UI in the app, or by editing `config.json` directly.

### Server Settings

Edit `serve.py` to change:

```python
PORT = 9099  # Web server port
```

## Deployment

### Simple (Recommended)

```bash
# Run in background
nohup python3 serve.py > folio.log 2>&1 &

# Or with systemd (create /etc/systemd/system/folio.service)
[Unit]
Description=Folio Book Manager
After=network.target

[Service]
Type=simple
User=youruser
WorkingDirectory=/path/to/folio
ExecStart=/usr/bin/python3 serve.py
Restart=always

[Install]
WantedBy=multi-user.target
```

### With nginx (Reverse Proxy)

```nginx
server {
    listen 443 ssl;
    server_name books.example.com;

    location / {
        proxy_pass http://localhost:9099;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

### Docker

**Using Docker Compose (Recommended):**

The `docker-compose.yml` file includes fields for all configuration options. Create a `.env` file:

```bash
# Calibre Library location (path to directory containing metadata.db)
CALIBRE_LIBRARY=/path/to/your/Calibre Library

# calibredb executable path (optional - auto-detected if not set)
CALIBREDB_PATH=/usr/bin/calibredb

# Hardcover API token (get from https://hardcover.app/account/api)
HARDCOVER_TOKEN=your-api-token

# Prowlarr address (e.g., http://prowlarr:9696 or http://localhost:9696)
PROWLARR_URL=http://prowlarr:9696

# Prowlarr API key (get from Prowlarr Settings → General → API Key)
PROWLARR_API_KEY=your-prowlarr-api-key
```

Then run:

```bash
docker-compose up -d
```

All configuration can also be managed through the Settings UI in the web interface.

**Manual Docker Build:**

```bash
# Build the image
docker build -t folio .

# Run the container
docker run -d \
  --name folio \
  -p 9099:9099 \
  -v /path/to/Calibre\ Library:/data/calibre-library:ro \
  -v $(pwd)/config.json:/app/config.json:rw \
  -e CALIBRE_LIBRARY=/data/calibre-library \
  -e CALIBREDB_PATH=/usr/bin/calibredb \
  -e HARDCOVER_TOKEN=your-api-token \
  -e PROWLARR_URL=http://prowlarr:9696 \
  -e PROWLARR_API_KEY=your-prowlarr-api-key \
  folio
```

**Note:** The Dockerfile is included in the repository. The `docker-compose.yml` file uses `build: .` to build from the included Dockerfile.

## Features in Detail

### Fuzzy Matching

When you search Hardcover, Folio automatically compares results with your library using fuzzy string matching. Books are marked "In Library" if:
- Title similarity > 85% AND author similarity > 50%
- OR both title and author similarity > 70%

This handles minor differences in titles (subtitles, editions) and author name formats.

### Book Requests

The Requests feature lets you:
1. Browse Hardcover and find books you want
2. Click "Request This Book" to add to your wish list
3. View all requests in the Requests tab
4. Cancel requests when no longer needed

Requests are stored locally in `config.json`.

### View Modes

**Grid View**: Traditional grid of book covers, ideal for browsing large libraries.

**Rows View**: Horizontal scrolling sections showing:
- Recently Added books
- Genre pills for quick filtering
- Author sections (for authors with 2+ books)

## Security Notes

- **No authentication** - Add a reverse proxy with auth for internet access
- **Local network recommended** - Server binds to all interfaces
- **API token security** - Hardcover token stored server-side, not exposed to browser
- **File uploads** - Cover art validated and processed via `calibredb`

## Troubleshooting

### "No books found"
- Check that your Calibre library path is correct
- Ensure `metadata.db` exists in the library folder
- Try restarting the server

### Hardcover search not working
- Verify your API token is correct
- Check the server console for error messages
- Ensure you have internet connectivity

### Metadata editing fails
- Calibre must be installed for `calibredb` command
- Folio automatically detects `calibredb` across platforms:
  - **PATH first** - Checks system PATH (most reliable)
  - **macOS**: `/Applications/calibre.app/Contents/MacOS/calibredb` and common user locations
  - **Linux**: `/usr/bin/calibredb`, `/usr/local/bin/calibredb`, `/opt/calibre/bin/calibredb`, and `~/.local/bin/calibredb`
  - **Windows**: `C:\Program Files\Calibre2\calibredb.exe` and user AppData locations
- If auto-detection fails, set `CALIBREDB_PATH` environment variable or configure it in Settings

## Design Philosophy

**Simple > Complex**
- Single Python file for the server
- No build process, no npm, no bundlers
- No external database (Calibre library is the source of truth)

**Mobile-First**
- Designed for phones and tablets
- Touch-friendly interface
- PWA support for app-like experience

**Beautiful by Default**
- Warm, inviting color palette
- Smooth animations and transitions
- Thoughtful typography and spacing

## Contributing

PRs welcome! Keep it simple - the goal is minimal dependencies and maximum functionality.

## License

MIT License

## Acknowledgments

- Inspired by [Overseerr](https://overseerr.dev/)'s clean UI
- Powered by [Calibre](https://calibre-ebook.com/)
- Book data from [Hardcover.app](https://hardcover.app/)
- Built with [Alpine.js](https://alpinejs.dev/) and [Tailwind CSS](https://tailwindcss.com/)

---

**Status**: Fully functional with Hardcover.app and Prowlarr integration

## Recent Updates

- **Cross-platform calibredb support** - Automatically detects calibredb on macOS, Linux, and Windows using PATH first, then platform-specific locations
- **Prowlarr integration** - Search for books via Prowlarr with configurable URL and API key
- **Enhanced Settings UI** - Manage Hardcover API key and Prowlarr configuration directly from Settings menu
- **Improved metadata descriptions** - Preserves paragraph layout and rich formatting (italics, links, etc.) when importing from iTunes, while removing bold tags
- **Docker Compose support** - Easy deployment with docker-compose.yml including all configuration fields
- **Reading List** - Mark books in your library as "reading list" items using Calibre custom columns
