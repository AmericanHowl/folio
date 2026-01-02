# 📚 Folio

A modern ebook management system for the rest of us.

**Folio** is "Overseerr for books" - a user-friendly interface to manage your Calibre library with better UX, especially designed for non-technical family members. Think of it as the missing web UI that makes Calibre accessible to everyone.

## 🎯 Project Goals

Replace calibre-web-automated with:
- 📱 **Better UX** - Large touch targets, simplified interface
- 👥 **Three Interfaces** - Kobo browser (touch-optimized), Mobile/Tablet (requests), Desktop (admin)
- 🔄 **Request-Based** - Manual review before downloads (not automatic)
- 🎨 **Modern Stack** - HTMX + Alpine.js + Tailwind CSS

## 📋 Development Roadmap

### Phase 1: Calibre Library Manager ✅ (Current)

**Component 1.1: Library Tab** - Browse and download existing Calibre books
- [x] List books from Calibre library
- [x] Search functionality
- [x] Download books to device
- [x] View book metadata
- [ ] Convert with kepubify
- [ ] Sync to Kobo
- [ ] Delete/organize books

### Phase 2: Book Acquisition (Future)

**Component 2.1: Explore Tab** - Discover new books
- Search via Hardcover API
- Browse popular/trending books

**Component 2.2: Requests Tab** - Manage download requests
- Request books (no automatic downloads)
- Manual review of Prowlarr/MAM results
- Auto-import to Calibre after approval
- Track request status: Requested → Searching → Ready
- Keep completed requests visible for 1 week

## 🏗️ Architecture

```
folio/
├── app/
│   ├── blueprints/          # Flask blueprints (routes)
│   │   ├── setup.py         # Initial configuration
│   │   ├── library.py       # Browse/download books
│   │   ├── requests.py      # Request queue (Phase 2)
│   │   └── explore.py       # Discover books (Phase 2)
│   ├── models/              # Database models
│   │   └── settings.py      # Configuration storage
│   ├── services/            # Business logic
│   │   └── calibre.py       # calibredb CLI wrapper
│   ├── templates/           # Jinja2 templates
│   └── static/              # CSS, JS, images
├── instance/                # Database files (gitignored)
├── requirements.txt         # Python dependencies
└── run.py                   # Application entry point
```

## 🚀 Quick Start

### Local Development (Mac/Linux)

1. **Clone and setup**:
   ```bash
   git clone <your-repo-url>
   cd folio
   python3 -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```

2. **Run the application**:
   ```bash
   python run.py
   ```

3. **Open browser**:
   ```
   http://localhost:9099
   ```

4. **Initial Setup**:
   - You'll be redirected to the setup page
   - Enter your Calibre library path (e.g., `/home/user/Calibre Library/`)
   - Enter your calibredb path (e.g., `/usr/bin/calibredb` on Linux, `/Applications/calibre.app/Contents/MacOS/calibredb` on Mac)
   - Click "Continue"

### Docker Deployment

1. **Update docker-compose.yml**:
   ```yaml
   volumes:
     # Update this path to your Calibre library
     - /path/to/your/calibre-library:/calibre-library:ro
   ```

2. **Build and run**:
   ```bash
   docker-compose up -d
   ```

3. **Access**:
   ```
   http://localhost:9099
   ```

## 🛠️ Tech Stack

- **Backend**: Python 3.11+ with Flask
- **Database**: SQLite (folio_config.db for settings)
- **Calibre Integration**: calibredb CLI wrapper (safer than direct DB access)
- **Frontend**: HTMX + Alpine.js + Tailwind CSS
- **Auth**: Planned Authentik OAuth (Phase 2)
- **Deployment**: Docker + docker-compose

## 📱 Three-Interface Design

### 1. Kobo Browser (Primary for Family)
- Large touch targets (minimum 48px)
- Simplified navigation
- Quick access to download books
- WebAuthn QR code login (planned)

### 2. Mobile/Tablet
- Request books remotely
- Check request status
- Browse library on the go

### 3. Desktop (Admin/Power User)
- Full library management
- Review and approve requests
- Configure settings
- Bulk operations

## 🔧 Configuration

All configuration is done via the web UI on first launch. Settings are stored in `instance/folio_config.db`.

**Required Settings**:
- Calibre Library Path
- calibredb Executable Path

**Find calibredb**:
- **Mac**: `/Applications/calibre.app/Contents/MacOS/calibredb`
- **Linux**: `/usr/bin/calibredb` or `/opt/calibre/calibredb`

## 📊 Current Features

- ✅ Web-based initial setup
- ✅ Browse Calibre library
- ✅ Search books by title/author/tags
- ✅ Download books
- ✅ Responsive design (mobile/tablet/desktop)
- ✅ Configurable paths via web UI
- ⏳ Kobo sync (planned)
- ⏳ kepubify conversion (planned)
- ⏳ Book requests (Phase 2)
- ⏳ Hardcover API integration (Phase 2)

## 🧪 Development

**Install dev dependencies**:
```bash
pip install -r requirements-dev.txt
```

**Run tests**:
```bash
pytest
```

**Code formatting**:
```bash
black app/
flake8 app/
```

## 📝 Environment Variables

Create a `.env` file (see `.env.example`):

```bash
FLASK_ENV=development
SECRET_KEY=your-secret-key-here
```

## 🤝 Contributing

This is currently a personal project, but contributions are welcome!

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

## 📄 License

MIT License (or your preferred license)

## 🙏 Acknowledgments

- Built to replace calibre-web-automated
- Inspired by Overseerr's request-based workflow
- Uses the excellent Calibre ecosystem

## 📞 Support

For issues or questions, please open a GitHub issue.

---

**Status**: Phase 1, Component 1.1 - Library Tab ✅
**Next**: Kobo sync and kepubify conversion
