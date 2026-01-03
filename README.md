# 📚 Folio

A modern, lightweight ebook management interface for Calibre libraries.

**Folio** is "Overseerr for books" - a clean, simple web app to browse and manage your Calibre library. Built with pure HTML/JS and a single Python script - no complex backend, no Docker required.

## ✨ Features

- 📖 **Browse your Calibre library** with a modern, card-based interface
- 🔍 **Real-time search** - Find books instantly
- ✏️ **Edit metadata** - Update titles, authors, publisher, descriptions, and cover art
- 📱 **Responsive design** - Works on desktop, tablet, and mobile
- 🎨 **Clean UI** - Overseerr-style hover effects and polished design
- ⚡ **Zero build step** - Pure HTML/JS with Alpine.js and Tailwind CSS

## 🚀 Quick Start

### Prerequisites

1. **Calibre** installed (for `calibredb` command)
2. **Python 3.7+** (standard library only, no pip installs needed!)

### Setup

1. **Start Calibre Content Server:**
   ```bash
   calibre-server --port 8080 "/path/to/your/Calibre Library"
   ```

2. **Start Folio:**
   ```bash
   # Set your Calibre library path (optional, defaults to ~/Calibre Library)
   export CALIBRE_LIBRARY="/path/to/your/Calibre Library"

   # Run the server
   python3 serve.py
   ```

3. **Open your browser:**
   ```
   http://localhost:9099
   ```

That's it! 🎉

## 📁 Project Structure

```
folio/
├── serve.py              # Single Python server (static files + metadata API)
├── public/               # Frontend files
│   ├── index.html       # Main app
│   └── js/
│       └── app.js       # Alpine.js app logic
└── README.md
```

## 🛠️ How It Works

Folio is intentionally simple:

1. **serve.py** - A single Python script that:
   - Serves static files from `public/`
   - Proxies read requests to Calibre Content Server
   - Handles metadata updates via `calibredb` CLI commands

2. **Frontend** - Pure HTML/JS with:
   - [Alpine.js](https://alpinejs.dev/) - Reactive UI (15KB)
   - [Tailwind CSS](https://tailwindcss.com/) - Styling (CDN)
   - [Bootstrap Icons](https://icons.getbootstrap.com/) - Icons
   - [Cal Sans](https://fonts.google.com/specimen/Cal+Sans) - Typography

3. **Calibre** - Your existing Calibre library:
   - Content Server provides read access (browse, search)
   - `calibredb` CLI provides write access (metadata editing)

## ⚙️ Configuration

Edit `serve.py` to customize:

```python
PORT = 9099                    # Web server port
CALIBRE_URL = "http://localhost:8080"  # Calibre Content Server URL
CALIBRE_LIBRARY = os.getenv('CALIBRE_LIBRARY', os.path.expanduser('~/Calibre Library'))
```

Or set environment variables:
```bash
export CALIBRE_LIBRARY="/custom/path/to/library"
python3 serve.py
```

## 📝 Metadata Editing

Folio lets you edit:
- **Title** - Book title
- **Authors** - Author names (comma-separated)
- **Publisher** - Publisher name
- **Description** - Book description/synopsis
- **Cover Art** - Upload new cover images (JPG, PNG, GIF)

Changes are written directly to your Calibre library using `calibredb` commands.

## 🎨 Design Philosophy

**Simple > Complex**
- Single Python file for the server
- No build process, no npm, no bundlers
- No database (Calibre library is the source of truth)
- No Docker complexity (though you can containerize if you want)

**Easy to Deploy**
- Copy the folder anywhere
- Run `python3 serve.py`
- That's it

**Easy to Maintain**
- Pure HTML/JS - view source to understand
- Python standard library only
- No dependencies to update
- No complex configurations

## 🚀 Deployment

### Simple (Recommended)

Just run `serve.py` on your server:
```bash
# Run in background with nohup
nohup python3 serve.py > folio.log 2>&1 &

# Or with systemd
sudo systemctl enable folio.service
sudo systemctl start folio
```

### With nginx (Reverse Proxy)

If you want HTTPS or custom domain:
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

### Docker (If You Really Want To)

```dockerfile
FROM python:3.11-slim
RUN apt-get update && apt-get install -y calibre
WORKDIR /app
COPY . .
EXPOSE 9099
CMD ["python3", "serve.py"]
```

## 🔐 Security Notes

- **No authentication** - Add a reverse proxy (nginx, Caddy) with auth if needed
- **Local network only** - `serve.py` binds to all interfaces; use firewall/proxy for internet access
- **File uploads** - Cover art uploads are validated (images only) and processed via `calibredb`

## 📋 Roadmap

Future features (maybe):
- [ ] Hardcover.app integration for metadata search
- [ ] EPUB → KEPUB conversion
- [ ] Multi-user support with authentication
- [ ] Book download tracking
- [ ] Reading progress sync

## 🤝 Contributing

This is a personal project, but PRs welcome! Keep it simple.

## 📄 License

MIT License

## 🙏 Acknowledgments

- Built to replace calibre-web-automated
- Inspired by Overseerr's clean UI
- Powered by [Calibre](https://calibre-ebook.com/)

---

**Current Status**: Fully functional for browsing and editing metadata ✅
