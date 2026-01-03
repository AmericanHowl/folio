# 📚 Folio

A modern ebook management system for the rest of us.

**Folio** is "Overseerr for books" - a lightweight static web app to manage your Calibre library with better UX, designed for non-technical family members. Pure HTML/JS/CSS with no backend required!

## 🏗️ Architecture

Folio uses a **modern static frontend** architecture:

```
┌──────────────────────────────────────┐
│   Static Frontend (public/)          │
│   • HTML + Alpine.js                 │
│   • Tailwind CSS (CDN)               │
│   • Vanilla JavaScript APIs          │
└─────────┬──────────────┬─────────────┘
          │              │
          ▼              ▼
   ┌─────────────┐  ┌──────────────┐
   │  Calibre    │  │  PocketBase  │
   │  Content    │  │  Database    │
   │  Server     │  │              │
   │  (port 8080)│  │  (port 8090) │
   └─────────────┘  └──────────────┘
```

**No Python/Flask backend!** Just static files + two services.

## 🎯 Project Goals

Replace calibre-web-automated with:
- 📱 **Better UX** - Large touch targets, simplified interface
- 🚀 **Static Frontend** - Fast, deployable anywhere
- 👥 **Multi-Device** - Kobo browser, mobile, tablet, desktop
- 🔄 **Request-Based** - Manual review before downloads
- 🎨 **Modern Stack** - Alpine.js + Tailwind CSS

## 🚀 Quick Start

### Option 1: Docker (Recommended)

1. **Start the services:**
   ```bash
   # Edit docker-compose.new.yml to set your Calibre library path
   docker-compose -f docker-compose.new.yml up -d
   ```

2. **Access Folio:**
   ```
   http://localhost:9099
   ```

3. **Configure:**
   - Click Settings (⚙️)
   - Calibre URL: `http://localhost:8080`
   - PocketBase URL: `http://localhost:8090`

### Option 2: Manual Setup

1. **Start Calibre Content Server:**
   ```bash
   calibre-server --port 8080 "/path/to/your/Calibre Library"
   ```

2. **Download & Run PocketBase:**
   ```bash
   # Download from https://pocketbase.io/docs/
   ./pocketbase serve --http=0.0.0.0:8090
   ```

3. **Serve static files:**
   ```bash
   # Any static web server works
   cd public
   python -m http.server 9099
   # Or use: npx serve -p 9099
   ```

4. **Open browser:**
   ```
   http://localhost:9099
   ```

## 📁 Project Structure

```
folio/
├── public/                # Static frontend (deploy this!)
│   ├── index.html        # Main app
│   ├── js/
│   │   ├── app.js        # Alpine.js app logic
│   │   ├── calibre-api.js    # Calibre API client
│   │   └── pocketbase-api.js # PocketBase client
│   └── css/              # Custom styles (if needed)
├── docker-compose.new.yml   # Docker setup
├── nginx.conf               # nginx proxy config
├── pocketbase-schema.json   # Database schema
└── README.md

Old Flask app (deprecated):
├── app/                  # ⚠️ No longer used
├── run.py                # ⚠️ No longer needed
└── requirements.txt      # ⚠️ Not needed
```

## 🛠️ Tech Stack

**Frontend:**
- Pure HTML5
- [Alpine.js](https://alpinejs.dev/) - Reactive UI (15KB)
- [Tailwind CSS](https://tailwindcss.com/) - Styling (CDN)
- Vanilla JavaScript - No build step!

**Backend Services:**
- [Calibre Content Server](https://manual.calibre-ebook.com/server.html) - Book library
- [PocketBase](https://pocketbase.io/) - Database (requests, prefs)

**Deployment:**
- Any static hosting (nginx, Caddy, Vercel, Netlify, GitHub Pages)
- Docker Compose for services
- Authentik for OAuth/SSO (optional)

## 📋 Development Roadmap

### Phase 1: Calibre Library Manager ✅ (Current)

**Component 1.1: Library Tab** - Browse existing Calibre books
- [x] List books from Calibre Content Server
- [x] Real-time search (client-side + server-side)
- [x] View book covers
- [x] Book metadata modal
- [ ] Download books to device
- [ ] Convert with kepubify
- [ ] Sync to Kobo

### Phase 2: Book Acquisition (Future)

**Component 2.1: Explore Tab** - Discover new books
- Search via Hardcover API
- Browse popular/trending books

**Component 2.2: Requests Tab** - Manage download requests
- Request books (stored in PocketBase)
- Manual review of Prowlarr/MAM results
- Real-time status updates
- Track: Requested → Searching → Ready
- Keep completed requests visible for 1 week

## 🔧 Configuration

Settings are stored in browser localStorage:
- `calibreUrl` - Calibre Content Server URL
- `pocketbaseUrl` - PocketBase URL

For production, you can:
1. Use environment variables
2. Hardcode URLs in `js/app.js`
3. Use nginx proxy (see `nginx.conf`)

## 🐳 Docker Deployment

The `docker-compose.new.yml` includes:

1. **calibre-server** - Serves your Calibre library
2. **pocketbase** - Stores requests and preferences
3. **nginx** - Serves static files + proxies APIs

**Update paths:**
```yaml
volumes:
  - /your/path/to/Calibre Library:/books  # ← Change this!
```

**Start everything:**
```bash
docker-compose -f docker-compose.new.yml up -d
```

## 📱 Three-Interface Design

### 1. Kobo Browser (Primary for Family)
- Large touch targets (48px minimum)
- Simplified navigation
- Quick access to download books
- Optimized for e-ink displays

### 2. Mobile/Tablet
- Request books remotely
- Check request status
- Browse library on the go

### 3. Desktop (Admin/Power User)
- Full library management
- Review and approve requests
- Configure settings
- Bulk operations

## 🔐 Authentication

Folio itself has **no auth**. Use a reverse proxy like Authentik, Authelia, or nginx with basic auth.

**Example with Authentik:**
```nginx
location /folio {
    auth_request /auth;
    proxy_pass http://folio:9099;
}
```

Authentik handles WebAuthn, OAuth, LDAP, etc.

## 📊 Current Features

- ✅ Static HTML/JS/CSS (no build step)
- ✅ Browse Calibre library via Content Server
- ✅ Real-time search (debounced)
- ✅ Book covers and metadata
- ✅ Responsive design (mobile/tablet/desktop)
- ✅ Settings modal (configure URLs)
- ✅ PocketBase integration ready
- ⏳ Book requests (Phase 2)
- ⏳ Hardcover API (Phase 2)
- ⏳ Download/sync features

## 🧪 Development

**Local development:**
```bash
# Serve static files
cd public
python -m http.server 9099

# Or use any static server
npx serve -p 9099
```

**Test Calibre API:**
```javascript
const api = new CalibreAPI('http://localhost:8080');
const books = await api.getBooks();
console.log(books);
```

**Test PocketBase:**
```javascript
const db = new FolioDatabase('http://localhost:8090');
await db.init();
const requests = await db.getRequests();
console.log(requests);
```

## 🚀 Deployment Options

### 1. Docker (Recommended)
See docker-compose.new.yml above

### 2. Static Hosting + Services
- Deploy `public/` to Vercel/Netlify/GitHub Pages
- Run Calibre Server on your NAS/server
- Run PocketBase on your NAS/server
- Configure URLs in settings

### 3. Self-Hosted with nginx
```nginx
server {
    listen 443 ssl;
    server_name folio.example.com;

    # Static files
    location / {
        root /var/www/folio/public;
        try_files $uri /index.html;
    }

    # Proxy to services
    location /calibre/ {
        proxy_pass http://localhost:8080/;
    }

    location /api/ {
        proxy_pass http://localhost:8090/;
    }
}
```

## 🤝 Contributing

This is a personal project, but contributions welcome!

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

## 📄 License

MIT License

## 🙏 Acknowledgments

- Built to replace calibre-web-automated
- Inspired by Overseerr's request-based workflow
- Uses Calibre Content Server API
- Powered by PocketBase for data persistence

---

**Status**: Phase 1, Component 1.1 - Static Frontend Complete ✅
**Next**: Download functionality and request management
