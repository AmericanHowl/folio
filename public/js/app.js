/**
 * Folio - Main Application
 * Modern book library interface with Hardcover.app integration
 */

// ============================================
// Client-side API Response Cache
// ============================================

const FolioCache = {
    // Cache TTLs in milliseconds
    TTL: {
        HARDCOVER_TRENDING: 5 * 60 * 1000,   // 5 minutes
        HARDCOVER_RECENT: 5 * 60 * 1000,     // 5 minutes
        HARDCOVER_LISTS: 10 * 60 * 1000,     // 10 minutes
        HARDCOVER_LIST: 10 * 60 * 1000,      // 10 minutes
        ITUNES_SEARCH: 30 * 60 * 1000,       // 30 minutes
    },

    /**
     * Get cached data if not expired
     */
    get(key) {
        try {
            const item = sessionStorage.getItem(`folio_cache_${key}`);
            if (!item) return null;

            const { data, expiry } = JSON.parse(item);
            if (Date.now() > expiry) {
                sessionStorage.removeItem(`folio_cache_${key}`);
                return null;
            }
            return data;
        } catch (e) {
            return null;
        }
    },

    /**
     * Cache data with TTL
     */
    set(key, data, ttl) {
        try {
            const item = {
                data,
                expiry: Date.now() + ttl
            };
            sessionStorage.setItem(`folio_cache_${key}`, JSON.stringify(item));
        } catch (e) {
            // Ignore storage errors (quota exceeded, etc.)
            console.warn('Cache storage failed:', e);
        }
    },

    /**
     * Clear all cache entries
     */
    clear() {
        try {
            const keysToRemove = [];
            for (let i = 0; i < sessionStorage.length; i++) {
                const key = sessionStorage.key(i);
                if (key && key.startsWith('folio_cache_')) {
                    keysToRemove.push(key);
                }
            }
            keysToRemove.forEach(key => sessionStorage.removeItem(key));
        } catch (e) {
            // Ignore errors
        }
    }
};

function folioApp() {
    return {
        // Setup state
        showSetup: true,
        setupStep: 1, // 1 = Hardcover API, 2 = Calibre Library, 3 = Prowlarr (optional)
        
        // Setup - Prowlarr
        prowlarrUrlInput: '',
        prowlarrApiKeyInput: '',
        validatingProwlarr: false,
        prowlarrError: '',
        prowlarrSuccess: false,
        
        // Library state
        books: [],
        sortedBooks: [],
        filteredBooks: [],
        libraryPages: [],
        currentPage: 0,
        booksPerPage: 12, // Will be calculated based on screen
        selectedBook: null,
        searchQuery: '',
        sortBy: 'recent',
        libraryView: 'grid', // 'list' or 'grid' - default to grid for main page
        bookshelfView: 'grid', // 'list' or 'grid' - default to grid for bookshelf
        booksPerPage: 10, // Books per page in list view
        currentListPage: 1, // Current page in list view
        libraryLoading: false,
        loadingMoreBooks: false, // Track if we're loading more books in background
        
        // Selection mode for bulk operations
        selectionMode: false,
        selectedBookIds: [],
        bulkActionLoading: false,
        
        // Edit mode for local books
        isEditMode: false,
        editingBook: null,
        allAuthors: [],
        allTags: [],
        authorSuggestions: [],
        tagSuggestions: [],
        showAuthorSuggestions: false,
        showTagSuggestions: false,

        // Configuration
        calibreLibraryPath: '',
        hardcoverToken: false,
        prowlarrUrl: '',
        prowlarrApiKey: false,
        
        // Setup - Hardcover API
        hardcoverApiKeyInput: '',
        validatingApiKey: false,
        apiKeyError: '',
        apiKeySuccess: false,
        
        // Setup - Calibre Browser
        browserPath: '',
        browserParent: null,
        browserEntries: [],
        verifyingCalibre: false,
        calibreError: '',
        
        // Hardcover data
        hardcoverLoading: false,
        hardcoverTrending: [],
        hardcoverTrendingMonth: [],
        hardcoverRecentReleases: [],
        hardcoverSections: [],
        loadingHardcoverLists: false,
        selectedHardcoverBook: null,
        
        // iTunes matching for local books
        selectedBookiTunesMatch: null,
        updatingMetadata: false,
        savingMetadata: false, // Track if we're saving edited metadata
        // iTunes metadata search in edit mode
        itunesMetadataResults: [], // Multiple results for user to pick from
        searchingItunesMetadata: false, // Loading state for metadata search

        // Requests
        requestedBooks: [],
        showRequests: false,
        
        // Prowlarr search
        selectedRequestBook: null,
        prowlarrSearchResults: [],
        prowlarrSortBy: 'seeders', // 'seeders', 'size', 'title'
        prowlarrSortOrder: 'desc', // 'asc', 'desc'
        searchingProwlarr: false,
        prowlarrError: null,
        downloadingProwlarr: null, // Track which result is being downloaded (by index)
        downloadProwlarrSuccess: null, // Track successful download (by index)
        downloadProwlarrError: null, // Track download error
        // Reading list (IDs of library books)
        readingListIds: [],
        readingListStatus: null, // 'added' | 'remove' | null
        
        // Settings
        showSettings: false,
        
        // Cache-buster for covers (persisted to localStorage to enable browser caching)
        coverVersion: parseInt(localStorage.getItem('coverVersion')) || 1,
        
        // Bookshelf view (for viewing full sections)
        showBookshelf: false,
        bookshelfTitle: '',
        bookshelfBooks: [],
        bookshelfType: '', // Track current bookshelf type for infinite scroll
        bookshelfHasMore: false, // Whether more books can be loaded
        loadingMoreBookshelf: false, // Prevent double-loading
        bookshelfSortBy: 'recent', // Sorting option for bookshelf

        // Search (iTunes)
        searchiTunesResults: [],
        searchiTunesPage: 0,
        searchiTunesHasMore: false,
        loadingSearchiTunes: false,

        // Back to top
        showBackToTop: false,

        // Camera capture state
        showCameraCapture: false,
        cameraState: 'initializing', // 'initializing' | 'ready' | 'captured' | 'identifying' | 'error'
        cameraError: '',
        cameraStream: null,
        capturedImageSrc: '',
        cameraRequestId: 0, // Used to track/cancel pending camera requests

        // Navigation state for browser history
        currentView: 'library', // 'library' | 'bookshelf' | 'requests'
        navigationLocked: false, // Prevent navigation loops
        headerCompact: false, // Whether the header title should be compact (on scroll)
        headerHidden: false, // Whether the header is hidden (scroll down = hide, scroll up = show)
        lastScrollY: 0, // Track last scroll position for direction detection

        /**
         * Initialize the application
         */
        async init() {
            console.log('📚 Initializing Folio...');
            
            // Calculate books per page based on screen size
            this.calculateBooksPerPage();
            window.addEventListener('resize', () => this.calculateBooksPerPage());

            // Back-to-top visibility, header compact state, scroll direction, and infinite scroll
            window.addEventListener('scroll', () => {
                const currentScrollY = window.scrollY;
                this.showBackToTop = currentScrollY > 400;

                // Detect scroll direction for header compact state
                // When scrolling down: hide search bar, show icons in section header
                // When scrolling up: show full header with search bar
                if (currentScrollY > 50) {
                    const scrollDiff = currentScrollY - this.lastScrollY;
                    // Only trigger if scrolled more than 5px to avoid micro-movements
                    if (scrollDiff > 5) {
                        // Scrolling down - compact header (hide search bar)
                        this.headerCompact = true;
                    } else if (scrollDiff < -5) {
                        // Scrolling up - expand header (show search bar)
                        this.headerCompact = false;
                    }
                } else {
                    // At top of page - always show full header
                    this.headerCompact = false;
                }
                this.lastScrollY = currentScrollY;

                // Infinite scroll for search results
                if (this.searchQuery && this.searchQuery.trim() && !this.loadingSearchiTunes && this.searchiTunesHasMore) {
                    const scrollPosition = window.innerHeight + currentScrollY;
                    const documentHeight = document.documentElement.scrollHeight;
                    // Load more when within 200px of bottom
                    if (scrollPosition >= documentHeight - 200) {
                        this.loadMoreiTunesSearch();
                    }
                }

                // Infinite scroll for bookshelf (grid view only)
                if (this.showBookshelf && this.bookshelfView === 'grid' && !this.loadingMoreBookshelf && this.bookshelfHasMore) {
                    const scrollPosition = window.innerHeight + currentScrollY;
                    const documentHeight = document.documentElement.scrollHeight;
                    // Load more when within 300px of bottom
                    if (scrollPosition >= documentHeight - 300) {
                        this.loadMoreBookshelf();
                    }
                }
            });

            // Browser history navigation (back/forward)
            window.addEventListener('popstate', (event) => {
                this.handleHistoryNavigation(event.state);
            });

            // Load server config
            await this.loadConfig();

            // Check if setup is needed (only Hardcover and Calibre are required)
            if (!this.hardcoverToken || !this.calibreLibraryPath) {
                this.showSetup = true;
                this.setupStep = !this.hardcoverToken ? 1 : 2;
                
                // If on step 2, open the browser
                if (this.setupStep === 2) {
                    await this.openBrowser();
                }
                
                console.log(`🔧 Setup needed - Step ${this.setupStep}`);
                return;
            }

            // Prowlarr is optional - don't force setup, just note it in settings

            // Setup complete, load the app
            this.showSetup = false;
            await this.loadApp();
        },

        /**
         * Calculate books per page based on screen width
         */
        calculateBooksPerPage() {
            const width = window.innerWidth;
            let cols = 3;
            if (width >= 1024) cols = 6;
            else if (width >= 768) cols = 5;
            else if (width >= 640) cols = 4;
            
            // 2 rows per page
            this.booksPerPage = cols * 2;
            
            // Recalculate pages if we have books
            if (this.sortedBooks.length > 0) {
                this.paginateBooks();
            }
        },

        /**
         * Load the main application data
         */
        async loadApp() {
            this.libraryLoading = true;
            
            try {
                // Load first 6 books immediately for fast initial display
                await this.loadBooks(6, 0, true);
                
                // Load requested books and reading list in parallel
                await Promise.all([
                    this.loadRequestedBooks(),
                    this.loadReadingList()
                ]);

                this.libraryLoading = false;

                // Load remaining books in background (non-blocking)
                // Load up to 500 more books (which should cover most libraries)
                this.loadBooks(494, 6, false);

                // Load Hardcover data asynchronously - prioritize recent releases
                this.loadHardcoverData();

            console.log('✅ Folio ready!');
            } catch (error) {
                console.error('Failed to load app:', error);
                this.libraryLoading = false;
            }

            // Restore previous view if page was refreshed
            this.restoreSavedView();

            // Periodically refresh library to pick up external changes
            // Only refresh if not searching (to prevent library view from reappearing)
            setInterval(() => {
                if (!this.libraryLoading && !this.showSetup && (!this.searchQuery || this.searchQuery.trim() === '')) {
                    this.loadBooks();
                }
            }, 60000);
        },

        /**
         * Load configuration from server
         */
        async loadConfig() {
            try {
                const response = await fetch('/api/config');
                const data = await response.json();
                this.calibreLibraryPath = data.calibre_library || '';
                this.hardcoverToken = data.hardcover_token || false;
                this.prowlarrUrl = data.prowlarr_url || '';
                this.prowlarrApiKey = data.prowlarr_api_key || false;
                
                // Populate input fields from loaded config (so env vars show in UI)
                if (data.hardcover_token && typeof data.hardcover_token === 'string') {
                    this.hardcoverApiKeyInput = data.hardcover_token;
                }
                if (data.prowlarr_url) {
                    this.prowlarrUrlInput = data.prowlarr_url;
                }
                // Note: prowlarr_api_key is sent as boolean for security, so we can't pre-populate it
                // But if prowlarrApiKey is true, we know it's configured
                
                console.log('📖 Loaded config:', {
                    library: this.calibreLibraryPath ? 'Set' : 'Not set',
                    token: this.hardcoverToken ? 'Set' : 'Not set',
                    prowlarr: this.prowlarrUrl ? 'Set' : 'Not set'
                });
            } catch (error) {
                console.error('Failed to load config:', error);
            }
        },

        /**
         * Navigation Management - Browser History Integration
         */

        /**
         * Push a new history state for navigation
         */
        pushHistoryState(view, data = {}) {
            if (this.navigationLocked) return;

            const state = { view, ...data };
            const url = `#${view}`;

            // Save to localStorage for page refresh restoration
            localStorage.setItem('folio_current_view', JSON.stringify(state));

            // Push to browser history
            history.pushState(state, '', url);
            this.currentView = view;
        },

        /**
         * Handle browser back/forward navigation
         */
        handleHistoryNavigation(state) {
            if (this.navigationLocked) return;

            this.navigationLocked = true;

            // If no state, we're back at library view
            if (!state || !state.view) {
                this.navigateToLibrary();
            } else {
                // Restore the view from history state
                switch (state.view) {
                    case 'library':
                        this.navigateToLibrary();
                        break;
                    case 'bookshelf':
                        this.navigateToBookshelf(state.title || 'Reading List');
                        break;
                    case 'requests':
                        this.navigateToRequests();
                        break;
                    default:
                        this.navigateToLibrary();
                }
            }

            setTimeout(() => {
                this.navigationLocked = false;
            }, 100);
        },

        /**
         * Initialize view on page load - always start at library
         */
        restoreSavedView() {
            // Always start at library view on page load/refresh
            this.currentView = 'library';
            this.showBookshelf = false;
            this.showRequests = false;
            localStorage.setItem('folio_current_view', JSON.stringify({ view: 'library' }));
            history.replaceState({ view: 'library' }, '', '#library');
        },

        /**
         * Navigate to library view
         */
        navigateToLibrary() {
            this.showBookshelf = false;
            this.showRequests = false;
            this.selectedBook = null;
            this.selectedHardcoverBook = null;
            this.showSettings = false;
            this.showCameraCapture = false;
            this.currentView = 'library';
            this.unlockBodyScroll();
            localStorage.setItem('folio_current_view', JSON.stringify({ view: 'library' }));
        },

        /**
         * Navigate to bookshelf view (reading list or Hardcover sections)
         */
        navigateToBookshelf(title) {
            this.showBookshelf = true;
            this.bookshelfTitle = title;
            this.showRequests = false;
            this.selectedBook = null;
            this.selectedHardcoverBook = null;
            this.showSettings = false;
            this.showCameraCapture = false;
            this.currentView = 'bookshelf';
            this.unlockBodyScroll();
        },

        /**
         * Navigate to requests view
         */
        navigateToRequests() {
            this.showRequests = true;
            this.showBookshelf = false;
            this.selectedBook = null;
            this.selectedHardcoverBook = null;
            this.showSettings = false;
            this.showCameraCapture = false;
            this.currentView = 'requests';
            this.unlockBodyScroll();
        },

        /**
         * Lock body scroll (for modals)
         */
        lockBodyScroll() {
            document.body.style.overflow = 'hidden';
            document.documentElement.style.overflow = 'hidden';
        },

        /**
         * Unlock body scroll
         */
        unlockBodyScroll() {
            document.body.style.overflow = '';
            document.documentElement.style.overflow = '';
        },

        /**
         * Validate Hardcover API key
         */
        async validateHardcoverKey() {
            let token = this.hardcoverApiKeyInput.trim();
            
            // Reset state
            this.apiKeyError = '';
            this.apiKeySuccess = false;
            
            // Strip "Bearer " prefix if user pasted the full token from Hardcover
            if (token.startsWith('Bearer ')) {
                token = token.substring(7);
            }
            
            if (!token) {
                this.apiKeyError = 'Please enter your API key from Hardcover';
                return;
            }
            
            this.validatingApiKey = true;
            
            try {
                // Save the token (Hardcover API uses raw token, not Bearer scheme)
                const saveResponse = await fetch('/api/config', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ hardcover_token: token }),
                });
                
                const saveResult = await saveResponse.json();
                
                if (!saveResult.success) {
                    this.apiKeyError = 'Failed to save API key: ' + (saveResult.error || 'Unknown error');
                    return;
                }
                
                // Test the connection
                const testResponse = await fetch('/api/hardcover/trending?limit=1');
                const testData = await testResponse.json();
                
                if (testData.error) {
                    this.apiKeyError = 'API key is invalid: ' + testData.error;
                    return;
                }
                
                // Success!
                this.apiKeySuccess = true;
                this.hardcoverToken = true;
                console.log('✅ Hardcover API key validated');
                
                // Move to next step after brief delay
                setTimeout(async () => {
                    this.setupStep = 2;
                    this.apiKeyError = '';
                    this.apiKeySuccess = false;
                    await this.openBrowser();
                }, 1000);
                
            } catch (error) {
                console.error('Failed to validate API key:', error);
                this.apiKeyError = 'Connection error: ' + error.message;
            } finally {
                this.validatingApiKey = false;
            }
        },

        /**
         * Open directory browser
         */
        async openBrowser() {
            const startPath = this.calibreLibraryPath || '~';
            await this.browseTo(startPath);
        },

        /**
         * Browse to a directory
         */
        async browseTo(path) {
            try {
                const response = await fetch(`/api/browse?path=${encodeURIComponent(path)}`);
                const data = await response.json();

                if (data.error) {
                    console.error('Browse error:', data.error);
                    this.calibreError = data.error;
                    return;
                }

                this.browserPath = data.path;
                this.browserParent = data.parent;
                this.browserEntries = data.entries;
                this.calibreError = '';
            } catch (error) {
                console.error('Failed to browse:', error);
                this.calibreError = 'Failed to browse directory: ' + error.message;
            }
        },

        /**
         * Select a Calibre library
         */
        selectCalibreLibrary(path) {
            this.calibreLibraryPath = path;
            this.calibreError = '';
            console.log('📚 Selected library:', path);
        },

        /**
         * Validate Prowlarr configuration
         */
        async validateProwlarr() {
            if (!this.prowlarrUrlInput.trim() || !this.prowlarrApiKeyInput.trim()) {
                this.prowlarrError = 'Please enter both URL and API key';
                return;
            }

            this.validatingProwlarr = true;
            this.prowlarrError = '';
            this.prowlarrSuccess = false;
            
            try {
                // Save Prowlarr config
                const response = await fetch('/api/config', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ 
                        prowlarr_url: this.prowlarrUrlInput.trim(),
                        prowlarr_api_key: this.prowlarrApiKeyInput.trim()
                    }),
                });
                
                const result = await response.json();
                
                if (!result.success) {
                    this.prowlarrError = 'Failed to save Prowlarr configuration: ' + (result.error || 'Unknown error');
                    return;
                }

                // Test connection using server-side validation endpoint (avoids CORS issues and provides logging)
                const validateResponse = await fetch('/api/prowlarr/validate', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        prowlarr_url: this.prowlarrUrlInput.trim(),
                        prowlarr_api_key: this.prowlarrApiKeyInput.trim()
                    })
                });
                
                const validateResult = await validateResponse.json();
                if (!validateResult.success) {
                    this.prowlarrError = validateResult.error || 'Failed to connect to Prowlarr. Please check your URL and API key.';
                    return;
                }
                
                this.prowlarrSuccess = true;
                this.prowlarrUrl = this.prowlarrUrlInput.trim();
                this.prowlarrApiKey = true;
                
                // Complete setup
                setTimeout(() => {
                    this.showSetup = false;
                    this.loadApp();
                }, 1000);
            } catch (error) {
                console.error('Failed to validate Prowlarr:', error);
                this.prowlarrError = 'Failed to connect to Prowlarr: ' + error.message;
            } finally {
                this.validatingProwlarr = false;
            }
        },

        /**
         * Skip Prowlarr setup
         */
        skipProwlarr() {
            this.showSetup = false;
            this.loadApp();
        },

        /**
         * Download from Prowlarr - send torrent/magnet to qBittorrent
         */
        async downloadFromProwlarr(result, book) {
            // Get the best available URL (prefer magnet, then download URL)
            const downloadUrl = result.magnetUrl || result.downloadUrl;
            
            if (!downloadUrl) {
                alert('No download URL available for this result. Try a different one.');
                return;
            }

            // Find the index of this result for tracking
            const resultIndex = this.prowlarrSearchResults.findIndex(r => r.guid === result.guid);
            
            // Reset previous error/success states
            this.downloadProwlarrError = null;
            this.downloadProwlarrSuccess = null;
            this.downloadingProwlarr = resultIndex;
            
            try {
                const response = await fetch('/api/qbittorrent/add', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        url: downloadUrl,
                        title: result.title
                    }),
                });

                const data = await response.json();

                if (data.success) {
                    console.log('✅ Torrent sent to qBittorrent:', result.title);
                    this.downloadProwlarrSuccess = resultIndex;
                    
                    // Clear success message after 3 seconds
                    setTimeout(() => {
                        if (this.downloadProwlarrSuccess === resultIndex) {
                            this.downloadProwlarrSuccess = null;
                        }
                    }, 3000);
                } else {
                    this.downloadProwlarrError = data.error || 'Failed to send to qBittorrent';
                    console.error('Download error:', this.downloadProwlarrError);
                    
                    // Clear error after 5 seconds
                    setTimeout(() => {
                        this.downloadProwlarrError = null;
                    }, 5000);
                }
            } catch (error) {
                console.error('Failed to send to qBittorrent:', error);
                this.downloadProwlarrError = 'Failed to send download. Please check qBittorrent configuration.';
                
                // Clear error after 5 seconds
                setTimeout(() => {
                    this.downloadProwlarrError = null;
                }, 5000);
            } finally {
                this.downloadingProwlarr = null;
            }
        },

        /**
         * Complete the setup process
         */
        async completeSetup() {
            if (!this.calibreLibraryPath) {
                this.calibreError = 'Please select a Calibre library directory';
                return;
            }

            this.verifyingCalibre = true;
            this.calibreError = '';
            
            try {
                // Save the library path
                const response = await fetch('/api/config', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ calibre_library: this.calibreLibraryPath }),
                });
                
                const result = await response.json();
                
                if (!result.success) {
                    this.calibreError = 'Failed to save library path: ' + (result.error || 'Unknown error');
                    return;
                }
                
                // Test that we can load books
                const testResponse = await fetch('/api/books?limit=1');
                const testData = await testResponse.json();
                
                if (!Array.isArray(testData)) {
                    this.calibreError = 'Could not read books from library. Make sure metadata.db exists.';
                    return;
                }

                console.log('✅ Setup complete!');
                
                // Move to step 3 (Prowlarr) or complete
                if (!this.prowlarrUrl || !this.prowlarrApiKey) {
                    this.setupStep = 3;
                } else {
                    // Hide setup and load app
                    this.showSetup = false;
                    await this.loadApp();
                }
                
                this.verifyingCalibre = false;
                
            } catch (error) {
                console.error('Failed to complete setup:', error);
                this.calibreError = 'Error: ' + error.message;
            } finally {
                this.verifyingCalibre = false;
            }
        },

        /**
         * Load books from Calibre database
         * @param {number} limit - Number of books to load (default: 500)
         * @param {number} offset - Offset for pagination (default: 0)
         * @param {boolean} isInitialLoad - If true, this is the initial load and should replace books array
         */
        async loadBooks(limit = 500, offset = 0, isInitialLoad = false) {
            try {
                if (!isInitialLoad && offset > 0) {
                    this.loadingMoreBooks = true;
                }
                
                const response = await fetch(`/api/books?limit=${limit}&offset=${offset}`);
                const newBooks = await response.json();
                
                if (isInitialLoad || offset === 0) {
                    // Replace all books for initial load
                    this.books = newBooks;
                    console.log(`📖 Loaded ${this.books.length} books from library`);
                } else {
                    // Append new books, avoiding duplicates
                    const existingIds = new Set(this.books.map(b => b.id));
                    const uniqueNewBooks = newBooks.filter(b => !existingIds.has(b.id));
                    this.books = [...this.books, ...uniqueNewBooks];
                    console.log(`📖 Loaded ${uniqueNewBooks.length} more books (total: ${this.books.length})`);
                }
                
                this.sortBooks();
            } catch (error) {
                console.error('Failed to load books:', error);
                if (isInitialLoad) {
                    this.books = [];
                    this.sortedBooks = [];
                    this.filteredBooks = [];
                }
            } finally {
                this.loadingMoreBooks = false;
            }
        },

        /**
         * Sort books based on selected sort option
         */
        sortBooks() {
            let sorted = [...this.books];

            switch (this.sortBy) {
                case 'recent':
                    sorted.sort((a, b) => {
                        const dateA = a.timestamp ? new Date(a.timestamp) : new Date(0);
                        const dateB = b.timestamp ? new Date(b.timestamp) : new Date(0);
                        return dateB - dateA;
                    });
                    break;
                case 'title':
                    sorted.sort((a, b) => (a.title || '').localeCompare(b.title || ''));
                    break;
                case 'title-desc':
                    sorted.sort((a, b) => (b.title || '').localeCompare(a.title || ''));
                    break;
                case 'author':
                    sorted.sort((a, b) => {
                        const authorA = this.formatAuthors(a.authors);
                        const authorB = this.formatAuthors(b.authors);
                        // Sort by last name (last word in the name)
                        const lastNameA = this.getLastNameForSort(authorA);
                        const lastNameB = this.getLastNameForSort(authorB);
                        return lastNameA.localeCompare(lastNameB);
                    });
                    break;
                case 'author-desc':
                    sorted.sort((a, b) => {
                        const authorA = this.formatAuthors(a.authors);
                        const authorB = this.formatAuthors(b.authors);
                        // Sort by last name (last word in the name)
                        const lastNameA = this.getLastNameForSort(authorA);
                        const lastNameB = this.getLastNameForSort(authorB);
                        return lastNameB.localeCompare(lastNameA);
                    });
                    break;
            }
            
            this.sortedBooks = sorted;
            // Only update filteredBooks if not searching (searchQuery should be empty)
            if (!this.searchQuery || this.searchQuery.trim() === '') {
                this.filteredBooks = sorted;
            }
            // Only paginate if in grid view
            if (this.libraryView === 'grid') {
                this.paginateBooks();
            }
            // Reset list page when sorting changes
            this.currentListPage = 1;
        },

        /**
         * Paginate books into pages for swipeable grid
         */
        paginateBooks() {
            this.libraryPages = [];
            for (let i = 0; i < this.sortedBooks.length; i += this.booksPerPage) {
                this.libraryPages.push(this.sortedBooks.slice(i, i + this.booksPerPage));
            }
            this.currentPage = 0;
        },

        /**
         * Update page indicator based on scroll position
         */
        updatePageIndicator() {
            const container = this.$refs.libraryPages;
            if (!container) return;
            
            const scrollLeft = container.scrollLeft;
            const pageWidth = container.offsetWidth;
            this.currentPage = Math.round(scrollLeft / pageWidth);
        },

        /**
         * Go to a specific page
         */
        goToPage(pageIndex) {
            const container = this.$refs.libraryPages;
            if (!container) return;
            
            container.scrollTo({
                left: pageIndex * container.offsetWidth,
                behavior: 'smooth'
            });
            this.currentPage = pageIndex;
        },

        /**
         * Load requested books from server
         */
        async loadRequestedBooks() {
            try {
                const response = await fetch('/api/requests');
                const data = await response.json();
                this.requestedBooks = data.books || [];
                console.log(`📋 Loaded ${this.requestedBooks.length} book requests`);
            } catch (error) {
                console.error('Failed to load requests:', error);
            }
        },

        /**
         * Load reading list (IDs of library books)
         */
        async loadReadingList() {
            try {
                const response = await fetch('/api/reading-list');
                const data = await response.json();
                this.readingListIds = Array.isArray(data.ids) ? data.ids : [];
                console.log(`📚 Reading list loaded: ${this.readingListIds.length} items`);
            } catch (error) {
                console.error('Failed to load reading list:', error);
                this.readingListIds = [];
            }
        },

        /**
         * Search books (library + iTunes)
         */
        async searchBooks() {
            const raw = this.searchQuery;
            const query = raw.toLowerCase().trim();

            if (!query) {
                this.filteredBooks = this.sortedBooks;
                this.searchiTunesResults = [];
                this.loadingSearchiTunes = false;
                this.searchiTunesHasMore = false;
                this.searchiTunesPage = 0;
                return;
            }

            // Don't filter local library - only show iTunes search results
            // Library matching is done via matchWithLibrary (same as hardcover lists)
            this.filteredBooks = [];

            // iTunes search (reset and load first page)
            this.searchiTunesResults = [];
            this.searchiTunesPage = 0;
            this.searchiTunesHasMore = true;
            await this.loadMoreiTunesSearch();
        },

        /**
         * Get top authors from library
         */
        getTopAuthors() {
            const authorCounts = {};
            this.books.forEach(book => {
                const author = Array.isArray(book.authors) ? book.authors[0] : book.authors;
                if (author) {
                    authorCounts[author] = (authorCounts[author] || 0) + 1;
                }
            });
            
            return Object.entries(authorCounts)
                .filter(([_, count]) => count >= 1)
                .sort((a, b) => b[1] - a[1])
                .slice(0, 10)
                .map(([author]) => author);
        },

        /**
         * Open book detail modal (local library)
         */
        openBookModal(book) {
            // Don't open modal if in selection mode
            if (this.selectionMode) {
                return;
            }

            this.selectedBook = book;
            this.selectedHardcoverBook = null;
            this.lockBodyScroll();

            // Check if book is already in reading list and set status accordingly
            if (this.isInReadingList(book.id)) {
                this.readingListStatus = 'remove';
                } else {
                this.readingListStatus = null;
            }
        },

        /**
         * Check if local book has an iTunes match (with client-side caching)
         */
        async checkiTunesMatch(book) {
            this.selectedBookiTunesMatch = null;
            
            try {
                const title = book.title;
                // Use formatted author (already normalized to "FirstName LastName")
                const author = this.formatAuthors(book.authors);
                // Extract first author if multiple
                const firstAuthor = author.split(',')[0].trim();
                const searchQuery = title + ' ' + firstAuthor;
                
                // Check client-side cache first
                const cacheKey = `itunes_match_${searchQuery}`;
                let data = FolioCache.get(cacheKey);
                
                if (!data) {
                    const response = await fetch(`/api/itunes/search?q=${encodeURIComponent(searchQuery)}&limit=5`);
                    data = await response.json();
                    // Cache even empty results to avoid repeated lookups
                    FolioCache.set(cacheKey, data, FolioCache.TTL.ITUNES_SEARCH);
                } else {
                    console.log(`📦 Cache hit: iTunes match for "${book.title}"`);
                }

                if (data.books && data.books.length > 0) {
                    // Find best match
                    for (const itunesBook of data.books) {
                        const titleMatch = this.calculateSimilarity(
                            this.normalizeForMatching(book.title),
                            this.normalizeForMatching(itunesBook.title)
                        );
                        // Compare formatted author with iTunes author
                        const authorMatch = this.calculateSimilarity(
                            this.normalizeForMatching(firstAuthor),
                            this.normalizeForMatching(itunesBook.author)
                        );
                        
                        if (titleMatch > 0.7 && authorMatch > 0.5) {
                            this.selectedBookiTunesMatch = itunesBook;
                            console.log(`🔗 Found iTunes match for "${book.title}"`);
                            break;
                        }
                    }
                }
            } catch (error) {
                console.error('Failed to check iTunes match:', error);
            }
        },

        /**
         * Update local book metadata from Hardcover match
         */
        async updateMetadataFromiTunes() {
            if (!this.selectedBook || !this.selectedBookiTunesMatch) return;
            
            this.updatingMetadata = true;
            
            try {
                const itunesBook = this.selectedBookiTunesMatch;
                const bookId = this.selectedBook.id;
                
                // Prepare metadata update with all fields
                // Combine existing tags with iTunes genres
                const existingTags = Array.isArray(this.selectedBook.tags) 
                    ? this.selectedBook.tags.join(', ') 
                    : (this.selectedBook.tags || '');
                const itunesGenres = itunesBook.genres && Array.isArray(itunesBook.genres) 
                    ? itunesBook.genres.join(', ') 
                    : '';
                const combinedTags = [existingTags, itunesGenres]
                    .filter(t => t && t.trim())
                    .join(', ');
                
                const updateData = {
                    title: itunesBook.title || undefined,
                    authors: itunesBook.author || undefined,
                    comments: itunesBook.description || undefined,
                    pubdate: itunesBook.year || undefined,
                    tags: combinedTags || undefined,
                    coverData: itunesBook.image || undefined, // Send URL, server will download
                };
                
                // Send update to server
                const response = await fetch(`/api/metadata-and-cover/${bookId}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(updateData),
                });

                const result = await response.json();

                if (result.success) {
                    console.log('✅ Metadata updated from iTunes');
                    
                    // Optimize: Update only the specific book instead of reloading all
                    const bookIndex = this.books.findIndex(b => b.id === bookId);
                    if (bookIndex !== -1) {
                        // Update the book in place with iTunes data (faster than fetching from server)
                        const book = this.books[bookIndex];
                        book.title = itunesBook.title || book.title;
                        book.authors = itunesBook.author ? [itunesBook.author] : book.authors;
                        book.comments = itunesBook.description || book.comments;
                        book.tags = itunesBook.genres && Array.isArray(itunesBook.genres) ? itunesBook.genres : book.tags;
                        if (itunesBook.year) {
                            book.pubdate = new Date(itunesBook.year, 0, 1).toISOString();
                        }
                        // Cover was updated
                        book.has_cover = true;
                        
                        // Update selected book reference
                        if (this.selectedBook && this.selectedBook.id === bookId) {
                            this.selectedBook = {...book};
                        }
                        
                        // Re-sort to reflect any changes (e.g., title change)
                        this.sortBooks();
                    }
                    
                    // Clear iTunes match after update
                    this.selectedBookiTunesMatch = null;
                    
                    // Bust cover cache so the new cover shows immediately
                    this.coverVersion = Date.now();
                    localStorage.setItem('coverVersion', this.coverVersion);
                } else {
                    console.error('Failed to update metadata:', result.errors);
                    alert('Failed to update metadata: ' + (result.errors?.join(', ') || 'Unknown error'));
                }
            } catch (error) {
                console.error('Failed to update metadata:', error);
                alert('Error updating metadata: ' + error.message);
            } finally {
                this.updatingMetadata = false;
            }
        },

        /**
         * Enter edit mode for the current book
         */
        async enterEditMode() {
            if (!this.selectedBook) return;
            
            // Load authors and tags for autocomplete
            if (this.allAuthors.length === 0) {
                try {
                    const authorsResp = await fetch('/api/authors');
                    this.allAuthors = await authorsResp.json();
                } catch (e) {
                    console.error('Failed to load authors:', e);
                }
            }
            
            if (this.allTags.length === 0) {
                try {
                    const tagsResp = await fetch('/api/tags');
                    this.allTags = await tagsResp.json();
                } catch (e) {
                    console.error('Failed to load tags:', e);
                }
            }
            
            // Clone book data for editing
            // Use formatAuthors to clean up duplicated authors
            const cleanAuthors = this.formatAuthors(this.selectedBook.authors);
            this.editingBook = {
                id: this.selectedBook.id,
                title: this.selectedBook.title || '',
                authors: cleanAuthors !== 'Unknown Author' ? cleanAuthors : '',
                year: this.selectedBook.pubdate ? new Date(this.selectedBook.pubdate).getFullYear().toString() : '',
                comments: this.selectedBook.comments || '',
                tags: Array.isArray(this.selectedBook.tags) 
                    ? this.selectedBook.tags.join(', ') 
                    : '',
                coverData: null,
                coverPreview: `/api/cover/${this.selectedBook.id}`,
            };
            
            this.isEditMode = true;
        },

        /**
         * Exit edit mode without saving
         */
        exitEditMode() {
            this.isEditMode = false;
            this.editingBook = null;
            this.authorSuggestions = [];
            this.tagSuggestions = [];
            this.showAuthorSuggestions = false;
            this.showTagSuggestions = false;
            this.itunesMetadataResults = [];
        },

        /**
         * Save edited metadata
         */
        async saveEditedMetadata() {
            if (!this.editingBook) return;
            
            this.savingMetadata = true;
            
            try {
                const updateData = {
                    title: this.editingBook.title,
                    authors: this.editingBook.authors,
                    comments: this.editingBook.comments,
                    tags: this.editingBook.tags,
                    pubdate: this.editingBook.year ? parseInt(this.editingBook.year) : undefined,
                    coverData: this.editingBook.coverData || undefined,
                };
                
                const response = await fetch(`/api/metadata-and-cover/${this.editingBook.id}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(updateData),
                });

                const result = await response.json();

                if (result.success) {
                    console.log('✅ Book metadata saved');
                    
                    // Optimize: Update only the specific book in the array instead of reloading all books
                    const bookIndex = this.books.findIndex(b => b.id === this.editingBook.id);
                    if (bookIndex !== -1) {
                        // Update the book in place with the data we sent (faster than fetching from server)
                        const book = this.books[bookIndex];
                        book.title = this.editingBook.title;
                        book.authors = this.editingBook.authors ? this.editingBook.authors.split(',').map(a => a.trim()).filter(a => a) : [];
                        book.comments = this.editingBook.comments || '';
                        book.tags = this.editingBook.tags ? this.editingBook.tags.split(',').map(t => t.trim()).filter(t => t) : [];
                        if (this.editingBook.year) {
                            book.pubdate = new Date(parseInt(this.editingBook.year), 0, 1).toISOString();
                        }
                        // Update has_cover if cover was updated
                        if (this.editingBook.coverData) {
                            book.has_cover = true;
                        }
                        
                        // Update selected book reference
                        if (this.selectedBook && this.selectedBook.id === this.editingBook.id) {
                            this.selectedBook = {...book};
                        }
                        
                        // Re-sort to reflect any changes (e.g., title change)
                        this.sortBooks();
                    }

                    // Bust cover cache so the new cover shows immediately
                    this.coverVersion = Date.now();
                    localStorage.setItem('coverVersion', this.coverVersion);

                    this.exitEditMode();
                } else {
                    alert('Failed to save metadata: ' + (result.errors?.join(', ') || 'Unknown error'));
                }
            } catch (error) {
                console.error('Failed to save metadata:', error);
                alert('Error saving metadata: ' + error.message);
            } finally {
                this.savingMetadata = false;
            }
        },

        /**
         * Handle cover upload/drop
         */
        handleCoverUpload(event) {
            const file = event.target.files?.[0] || event.dataTransfer?.files?.[0];
            if (!file || !file.type.startsWith('image/')) return;
            
                const reader = new FileReader();
                reader.onload = (e) => {
                    this.editingBook.coverData = e.target.result;
                this.editingBook.coverPreview = e.target.result;
                };
                reader.readAsDataURL(file);
        },

        /**
         * Handle book file upload
         */
        async handleBookUpload(event) {
            const files = event.target.files;
            if (!files || files.length === 0) return;

            const validExtensions = ['.epub', '.pdf', '.mobi', '.azw', '.azw3', '.fb2', '.lit', '.prc', '.txt', '.rtf', '.djvu', '.cbz', '.cbr'];
            const validFiles = Array.from(files).filter(file => {
                const ext = '.' + file.name.split('.').pop().toLowerCase();
                return validExtensions.includes(ext);
            });

            if (validFiles.length === 0) {
                alert('No valid book files selected. Supported formats: EPUB, PDF, MOBI, AZW, AZW3, FB2, LIT, PRC, TXT, RTF, DJVU, CBZ, CBR');
                event.target.value = '';
                return;
            }

            try {
                const formData = new FormData();
                validFiles.forEach(file => {
                    formData.append('files', file);
                });

                const response = await fetch('/api/upload-books', {
                    method: 'POST',
                    body: formData
                });

                const result = await response.json();

                if (result.success) {
                    alert(`Successfully uploaded ${validFiles.length} book file(s). They will be imported shortly.`);
                    // Reload books after a delay to show newly imported books
                    setTimeout(() => {
                        this.loadBooks();
                    }, 2000);
                } else {
                    alert('Upload failed: ' + (result.error || 'Unknown error'));
                }
            } catch (error) {
                console.error('Upload error:', error);
                alert('Error uploading files: ' + error.message);
            } finally {
                // Reset file input
                event.target.value = '';
            }
        },

        /**
         * Filter author suggestions
         */
        filterAuthorSuggestions() {
            if (!this.editingBook.authors) {
                this.authorSuggestions = [];
                this.showAuthorSuggestions = false;
                    return;
                }

            const query = this.editingBook.authors.split(',').pop().trim().toLowerCase();
            if (query.length < 2) {
                this.authorSuggestions = [];
                this.showAuthorSuggestions = false;
                return;
            }
            
            this.authorSuggestions = this.allAuthors
                .filter(a => a.toLowerCase().includes(query))
                .slice(0, 5);
            this.showAuthorSuggestions = this.authorSuggestions.length > 0;
        },

        /**
         * Select author from suggestions
         */
        selectAuthor(author) {
            const parts = this.editingBook.authors.split(',');
            parts[parts.length - 1] = author;
            this.editingBook.authors = parts.join(', ');
            this.showAuthorSuggestions = false;
        },

        /**
         * Filter tag suggestions
         */
        filterTagSuggestions() {
            if (!this.editingBook.tags) {
                this.tagSuggestions = [];
                this.showTagSuggestions = false;
                return;
            }

            const query = this.editingBook.tags.split(',').pop().trim().toLowerCase();
            if (query.length < 2) {
                this.tagSuggestions = [];
                this.showTagSuggestions = false;
                return;
            }
            
            this.tagSuggestions = this.allTags
                .filter(t => t.toLowerCase().includes(query))
                .slice(0, 8);
            this.showTagSuggestions = this.tagSuggestions.length > 0;
        },

        /**
         * Select tag from suggestions
         */
        selectTag(tag) {
            const parts = this.editingBook.tags.split(',');
            parts[parts.length - 1] = tag;
            this.editingBook.tags = parts.join(', ');
            this.showTagSuggestions = false;
        },

        /**
         * Close book modal
         */
        closeBookModal() {
            this.selectedBook = null;
            this.selectedBookHardcoverMatch = null;
            this.exitEditMode();
            this.unlockBodyScroll();
        },

        /**
         * Search iTunes for metadata options (shows multiple results for user to pick)
         */
        async searchItunesForMetadata() {
            if (!this.editingBook) return;

            this.itunesMetadataResults = [];
            this.searchingItunesMetadata = true;

            try {
                const title = this.editingBook.title;
                const author = this.editingBook.authors || '';
                const firstAuthor = author.split(',')[0].trim();
                const searchQuery = title + (firstAuthor ? ' ' + firstAuthor : '');

                // Check client-side cache first
                const cacheKey = `itunes_metadata_${searchQuery}`;
                let data = FolioCache.get(cacheKey);

                if (!data) {
                    const response = await fetch(`/api/itunes/search?q=${encodeURIComponent(searchQuery)}&limit=5`);
                    data = await response.json();
                    FolioCache.set(cacheKey, data, FolioCache.TTL.ITUNES_SEARCH);
                } else {
                    console.log(`📦 Cache hit: iTunes metadata for "${title}"`);
                }

                if (data.books && data.books.length > 0) {
                    // Return top 3 results for user to choose
                    this.itunesMetadataResults = data.books.slice(0, 3);
                    console.log(`🔍 Found ${this.itunesMetadataResults.length} iTunes results for "${title}"`);
                }
            } catch (error) {
                console.error('Failed to search iTunes for metadata:', error);
            } finally {
                this.searchingItunesMetadata = false;
            }
        },

        /**
         * Apply selected iTunes result to the editing form
         */
        applyItunesMetadata(itunesBook) {
            if (!this.editingBook || !itunesBook) return;

            // Apply metadata to editing form
            if (itunesBook.title) this.editingBook.title = itunesBook.title;
            if (itunesBook.author) this.editingBook.authors = itunesBook.author;
            if (itunesBook.year) this.editingBook.year = itunesBook.year.toString();
            if (itunesBook.description) this.editingBook.comments = itunesBook.description;
            if (itunesBook.genres && Array.isArray(itunesBook.genres)) {
                // Combine with existing tags
                const existingTags = this.editingBook.tags ? this.editingBook.tags.split(',').map(t => t.trim()).filter(t => t) : [];
                const newTags = [...new Set([...existingTags, ...itunesBook.genres])];
                this.editingBook.tags = newTags.join(', ');
            }
            if (itunesBook.image) {
                this.editingBook.coverPreview = itunesBook.image;
                this.editingBook.coverData = itunesBook.image; // URL will be downloaded by server
            }

            // Clear results after selection
            this.itunesMetadataResults = [];
            console.log(`✅ Applied iTunes metadata from "${itunesBook.title}"`);
        },

        // ============================================
        // Reading List
        // ============================================

        isInReadingList(bookId) {
            return this.readingListIds.includes(bookId);
        },

        /**
         * Toggle reading list for a local library book (from modal)
         */
        async toggleReadingListFromLibrary() {
            if (!this.selectedBook) return;
            const bookId = this.selectedBook.id;

            if (this.isInReadingList(bookId)) {
                // Remove from reading list
                await this.removeFromReadingList(bookId);
                this.readingListStatus = null;
            } else {
                // Add to reading list
                await this.addToReadingList(bookId);
                this.readingListStatus = 'added';

                // After a short delay, change label to "Remove from Reading List"
                setTimeout(() => {
                    if (this.selectedBook && this.selectedBook.id === bookId) {
                        this.readingListStatus = 'remove';
                    }
                }, 1200);
            }
        },

        async addToReadingList(bookId) {
            try {
                const response = await fetch('/api/reading-list', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ book_id: bookId }),
                });
                const data = await response.json();
                if (data.success && Array.isArray(data.ids)) {
                    this.readingListIds = [...data.ids]; // Create new array for reactivity
                    console.log(`🔖 Added to reading list: ${bookId}`);
                }
            } catch (error) {
                console.error('Failed to add to reading list:', error);
            }
        },

        async removeFromReadingList(bookId) {
            try {
                const response = await fetch(`/api/reading-list/${bookId}`, {
                    method: 'DELETE',
                });
                const data = await response.json();
                if (data.success && Array.isArray(data.ids)) {
                    this.readingListIds = [...data.ids]; // Create new array for reactivity
                    console.log(`🗑️ Removed from reading list: ${bookId}`);
                }
            } catch (error) {
                console.error('Failed to remove from reading list:', error);
            }
        },

        /**
         * Toggle reading list for a book (used in library list view)
         */
        async toggleReadingList(bookId) {
            try {
                if (this.isInReadingList(bookId)) {
                    await this.removeFromReadingList(bookId);
                } else {
                    await this.addToReadingList(bookId);
                }
                // Force reactivity update
                this.$nextTick(() => {});
            } catch (error) {
                console.error('Failed to toggle reading list:', error);
            }
        },

        /**
         * Add matched library book to reading list from Hardcover modal
         */
        async addLibraryBookToReadingList(hardcoverBook) {
            if (!hardcoverBook || !hardcoverBook.libraryBookId) return;
            const bookId = hardcoverBook.libraryBookId;
            await this.addToReadingList(bookId);
        },

        /**
         * Open Hardcover book modal
         */
        openHardcoverModal(book) {
            this.selectedHardcoverBook = this.enrichHardcoverBook(book);
            this.selectedBook = null;
            this.lockBodyScroll();
        },

        /**
         * Enrich a Hardcover book with library matching
         */
        enrichHardcoverBook(book) {
            const libraryMatch = this.findLibraryMatch(book);
            const isRequested = this.requestedBooks.some(r => r.id === book.id);
            
            return {
                ...book,
                inLibrary: !!libraryMatch,
                libraryBookId: libraryMatch?.id,
                requested: isRequested
            };
        },

        // ============================================
        // Hardcover Integration
        // ============================================

        /**
         * Load all Hardcover data in parallel for maximum performance
         */
        async loadHardcoverData() {
            if (!this.hardcoverToken) return;

            this.hardcoverLoading = true;
            
            try {
                // Load ALL Hardcover data in parallel for faster loading
                await Promise.all([
                    this.loadHardcoverRecent(),
                    this.loadHardcoverTrending(),
                    this.loadHardcoverTrendingMonth(),
                    this.loadHardcoverLists()
                ]);
                
                console.log('✅ Hardcover data loaded (parallel)');
            } catch (error) {
                console.error('❌ Failed to load Hardcover data:', error);
            } finally {
                this.hardcoverLoading = false;
            }
        },

        /**
         * Load trending books (with client-side caching)
         */
        async loadHardcoverTrending() {
            const cacheKey = 'hardcover_trending_20';
            
            // Check client-side cache first
            const cached = FolioCache.get(cacheKey);
            if (cached) {
                this.hardcoverTrending = this.matchWithLibrary(cached.books || []);
                console.log(`📦 Cache hit: ${this.hardcoverTrending.length} trending books`);
                return;
            }

            try {
                const response = await fetch('/api/hardcover/trending?limit=20');
                const data = await response.json();

                if (data.error) {
                    console.error('Trending error:', data.error);
                    this.hardcoverTrending = [];
                } else {
                    this.hardcoverTrending = this.matchWithLibrary(data.books || []);
                    // Cache the raw API response
                    FolioCache.set(cacheKey, data, FolioCache.TTL.HARDCOVER_TRENDING);
                    console.log(`📈 Loaded ${this.hardcoverTrending.length} trending books`);
                }
            } catch (error) {
                console.error('Failed to load trending:', error);
                this.hardcoverTrending = [];
            }
        },

        /**
         * Load most popular releases from 2025 (with client-side caching)
         */
        async loadHardcoverTrendingMonth() {
            const cacheKey = 'hardcover_trending_month_20';
            
            // Check client-side cache first
            const cached = FolioCache.get(cacheKey);
            if (cached) {
                this.hardcoverTrendingMonth = this.matchWithLibrary(cached.books || []);
                console.log(`📦 Cache hit: ${this.hardcoverTrendingMonth.length} popular 2025 books`);
                return;
            }

            try {
                const response = await fetch('/api/hardcover/trending?limit=20');
                const data = await response.json();

                if (data.error) {
                    console.error('Trending month error:', data.error);
                    this.hardcoverTrendingMonth = [];
                } else {
                    this.hardcoverTrendingMonth = this.matchWithLibrary(data.books || []);
                    // Cache the raw API response
                    FolioCache.set(cacheKey, data, FolioCache.TTL.HARDCOVER_TRENDING);
                    console.log(`📈 Loaded ${this.hardcoverTrendingMonth.length} popular 2025 books`);
                }
            } catch (error) {
                console.error('Failed to load trending month:', error);
                this.hardcoverTrendingMonth = [];
            }
        },

        /**
         * Load recent releases (with client-side caching)
         */
        async loadHardcoverRecent() {
            const cacheKey = 'hardcover_recent_20';
            
            // Check client-side cache first
            const cached = FolioCache.get(cacheKey);
            if (cached) {
                this.hardcoverRecentReleases = this.matchWithLibrary(cached.books || []);
                console.log(`📦 Cache hit: ${this.hardcoverRecentReleases.length} recent releases`);
                return;
            }

            try {
                const response = await fetch('/api/hardcover/recent?limit=20');
                const data = await response.json();
                
                if (data.error) {
                    console.error('Recent releases error:', data.error);
                    this.hardcoverRecentReleases = [];
                } else {
                    this.hardcoverRecentReleases = this.matchWithLibrary(data.books || []);
                    // Cache the raw API response
                    FolioCache.set(cacheKey, data, FolioCache.TTL.HARDCOVER_RECENT);
                    console.log(`🆕 Loaded ${this.hardcoverRecentReleases.length} recent releases`);
                }
            } catch (error) {
                console.error('Failed to load recent releases:', error);
                this.hardcoverRecentReleases = [];
            }
        },

        /**
         * Load curated lists from @hardcover (with client-side caching)
         */
        async loadHardcoverLists() {
            // Prevent multiple simultaneous loads
            if (this.loadingHardcoverLists) {
                return;
            }

            this.loadingHardcoverLists = true;

            try {
                // Clear sections first to prevent showing stale data
                this.hardcoverSections = [];
                
                const response = await fetch('/api/hardcover/lists');
                const data = await response.json();
                
                if (data.error || !data.lists || data.lists.length === 0) {
                    console.error('Lists error:', data.error);
                    this.hardcoverSections = [];
                    return;
                }

                // Use all lists returned (already randomly selected from top 25)
                const selectedLists = data.lists.slice(0, 3);
                
                // Load books from selected lists in parallel
                const listPromises = selectedLists.map(list => this.loadHardcoverList(list.id));
                const results = await Promise.all(listPromises);
                
                // Set sections atomically to prevent glitching - only set valid sections with books
                const validSections = results.filter(result => result.books && result.books.length > 0);
                // Set all at once to prevent incremental updates
                this.hardcoverSections = [...validSections];
                console.log(`📚 Loaded ${this.hardcoverSections.length} curated lists (parallel)`);
            } catch (error) {
                console.error('Failed to load lists:', error);
                this.hardcoverSections = [];
            } finally {
                this.loadingHardcoverLists = false;
            }
        },

        /**
         * Load books from a specific list (with client-side caching)
         */
        async loadHardcoverList(listId) {
            const cacheKey = `hardcover_list_${listId}_20`;
            
            // Check client-side cache first
            const cached = FolioCache.get(cacheKey);
            if (cached) {
                console.log(`📦 Cache hit: list ${listId}`);
                return {
                    id: listId,
                    books: this.matchWithLibrary(cached.books || []),
                    name: cached.list_name || '',
                    description: cached.list_description || ''
                };
            }

            try {
                const response = await fetch(`/api/hardcover/list?id=${listId}&limit=20`);
                const data = await response.json();

                if (data.error) {
                    return { id: listId, books: [], name: '', description: '' };
                }
                
                // Cache the raw API response
                FolioCache.set(cacheKey, data, FolioCache.TTL.HARDCOVER_LIST);
                
                return {
                    id: listId,
                    books: this.matchWithLibrary(data.books || []),
                    name: data.list_name || '',
                    description: data.list_description || ''
                };
            } catch (error) {
                console.error(`Failed to load list ${listId}:`, error);
                return { id: listId, books: [], name: '', description: '' };
            }
        },

        /**
         * Match Hardcover books with local library
         */
        matchWithLibrary(hardcoverBooks) {
            return hardcoverBooks.map(book => {
                const libraryMatch = this.findLibraryMatch(book);
                const isRequested = this.requestedBooks.some(r => r.id === book.id);

                return {
                    ...book,
                    inLibrary: !!libraryMatch,
                    libraryBookId: libraryMatch?.id,
                    requested: isRequested
                };
            });
        },

        /**
         * Load more iTunes search results (incremental, with client-side caching)
         */
        async loadMoreiTunesSearch() {
            if (!this.searchQuery.trim()) {
                return;
            }
            if (this.loadingSearchiTunes || !this.searchiTunesHasMore) {
                return;
            }

            this.loadingSearchiTunes = true;
            const pageSize = 20;
            const nextPage = this.searchiTunesPage + 1;
            const offset = (nextPage - 1) * pageSize;

            // Check client-side cache first
            const cacheKey = `itunes_search_${this.searchQuery}_${pageSize}_${offset}`;
            const cached = FolioCache.get(cacheKey);
            
            try {
                let data;
                if (cached) {
                    data = cached;
                    console.log(`📦 Cache hit: iTunes search '${this.searchQuery}' page ${nextPage}`);
                } else {
                    const response = await fetch(`/api/itunes/search?q=${encodeURIComponent(this.searchQuery)}&limit=${pageSize}&offset=${offset}`);
                    data = await response.json();
                    // Cache the response
                    if (data.books) {
                        FolioCache.set(cacheKey, data, FolioCache.TTL.ITUNES_SEARCH);
                    }
                }

                if (data.books && data.books.length > 0) {
                    const books = this.matchWithLibrary(data.books);
                    // Filter out duplicates and append new results
                    const existingIds = new Set(this.searchiTunesResults.map(b => b.id));
                    const newBooks = books.filter(book => !existingIds.has(book.id));
                    // Append new results - create new array to ensure Alpine.js reactivity
                    this.searchiTunesResults = [...this.searchiTunesResults, ...newBooks];
                    this.searchiTunesPage = nextPage;
                    this.searchiTunesHasMore = data.books.length >= pageSize;
                } else {
                    this.searchiTunesHasMore = false;
                }
            } catch (error) {
                console.error('Failed to load iTunes search results:', error);
                this.searchiTunesHasMore = false;
            } finally {
                this.loadingSearchiTunes = false;
            }
        },

        /**
         * Find a matching book in the local library
         */
        findLibraryMatch(hardcoverBook) {
            const hcTitle = this.normalizeForMatching(hardcoverBook.title);
            const hcAuthor = this.normalizeForMatching(hardcoverBook.author);

            for (const book of this.books) {
                const libTitle = this.normalizeForMatching(book.title);
                const libAuthor = this.normalizeForMatching(
                    Array.isArray(book.authors) ? book.authors.join(' ') : book.authors
                );

                const titleSimilarity = this.calculateSimilarity(hcTitle, libTitle);
                const authorSimilarity = this.calculateSimilarity(hcAuthor, libAuthor);

                if (titleSimilarity > 0.85 && authorSimilarity > 0.5) {
                    return book;
                }

                if (titleSimilarity > 0.7 && authorSimilarity > 0.7) {
                    return book;
                }
            }

            return null;
        },

        /**
         * Normalize a string for fuzzy matching
         */
        normalizeForMatching(str) {
            if (!str) return '';
            // Remove subtitle (text after colon) for better matching
            let normalized = str.split(':')[0].trim();
            return normalized
                .toLowerCase()
                .replace(/[^a-z0-9\s]/g, '')
                .replace(/\s+/g, ' ')
                .trim();
        },

        /**
         * Calculate similarity between two strings
         */
        calculateSimilarity(str1, str2) {
            if (!str1 || !str2) return 0;
            if (str1 === str2) return 1;

            const words1 = new Set(str1.split(' ').filter(w => w.length > 2));
            const words2 = new Set(str2.split(' ').filter(w => w.length > 2));

            if (words1.size === 0 || words2.size === 0) {
                if (str1.includes(str2) || str2.includes(str1)) return 0.8;
                return 0;
            }

            const intersection = [...words1].filter(w => words2.has(w));
            const union = new Set([...words1, ...words2]);

            return intersection.length / union.size;
        },

        /**
         * View a Hardcover book in local library
         */
        viewInLibrary(hardcoverBook) {
            if (hardcoverBook.libraryBookId) {
                const book = this.books.find(b => b.id === hardcoverBook.libraryBookId);
                if (book) {
                    this.selectedHardcoverBook = null;
                    this.openBookModal(book);
                }
            }
        },

        // ============================================
        // Request Management
        // ============================================

        /**
         * Request a book
         */
        async requestBook(book) {
            try {
                const response = await fetch('/api/requests', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ book }),
                });

                const data = await response.json();
                if (data.success) {
                    this.requestedBooks = data.books;
                    book.requested = true;
                    console.log(`📬 Requested: ${book.title}`);
                    return true;
                } else {
                    console.error('Failed to request book:', data.error);
                    alert('Failed to add book to requests. Please try again.');
                    return false;
                }
            } catch (error) {
                console.error('Failed to request book:', error);
                alert('Failed to add book to requests. Please try again.');
                return false;
            }
        },

        /**
         * Request a book (keep modal open, button will change to Cancel)
         */
        async requestBookAndClose() {
            if (this.selectedHardcoverBook) {
                await this.requestBook(this.selectedHardcoverBook);
                // Don't close modal - let the button state change to "Cancel Request"
            }
        },

        /**
         * Cancel a book request
         */
        async cancelRequest(book) {
            try {
                const response = await fetch(`/api/requests/${book.id}`, {
                    method: 'DELETE',
                });

                const data = await response.json();
                if (data.success) {
                    this.requestedBooks = data.books;
                    book.requested = false;
                    console.log(`🗑️ Cancelled request: ${book.title}`);
                }
            } catch (error) {
                console.error('Failed to cancel request:', error);
            }
        },

        // ============================================
        // Bookshelf View
        // ============================================

        /**
         * Open bookshelf view with a section's books (with client-side caching)
         */
        async openBookshelf(type, title) {
            this.bookshelfTitle = title;
            this.bookshelfBooks = [];
            this.bookshelfView = 'grid'; // Default to grid view for bookshelf
            this.bookshelfType = type; // Track type for infinite scroll
            this.bookshelfHasMore = false; // Will be set based on results
            this.bookshelfSortBy = 'recent'; // Reset sort
            this.currentListPage = 1; // Reset to first page
            this.showBookshelf = true;

            // Load 30 books for the bookshelf
            try {
                let cacheKey;
                let data;

                switch (type) {
                    case 'library':
                        this.bookshelfBooks = this.sortedBooks.slice(0, 30);
                        this.bookshelfHasMore = this.sortedBooks.length > 30;
                        return;
                    case 'library-all':
                        this.bookshelfBooks = this.sortedBooks;
                        this.bookshelfHasMore = false; // All loaded
                        return;
                    case 'trending':
                        cacheKey = 'bookshelf_trending_30';
                        data = FolioCache.get(cacheKey);
                        if (!data) {
                            const response = await fetch('/api/hardcover/trending?limit=30');
                            data = await response.json();
                            if (data.books) {
                                FolioCache.set(cacheKey, data, FolioCache.TTL.HARDCOVER_TRENDING);
                            }
                        }
                        break;
                    case 'trending-month':
                        cacheKey = 'bookshelf_trending_month_30';
                        data = FolioCache.get(cacheKey);
                        if (!data) {
                            const response = await fetch('/api/hardcover/trending?limit=30');
                            data = await response.json();
                            if (data.books) {
                                FolioCache.set(cacheKey, data, FolioCache.TTL.HARDCOVER_TRENDING);
                            }
                        }
                        break;
                    case 'recent':
                        cacheKey = 'bookshelf_recent_30';
                        data = FolioCache.get(cacheKey);
                        if (!data) {
                            const response = await fetch('/api/hardcover/recent?limit=30');
                            data = await response.json();
                            if (data.books) {
                                FolioCache.set(cacheKey, data, FolioCache.TTL.HARDCOVER_RECENT);
                            }
                        }
                        break;
                    case 'author':
                        cacheKey = `bookshelf_author_${this.hardcoverAuthor}_30`;
                        data = FolioCache.get(cacheKey);
                        if (!data) {
                            const response = await fetch(`/api/hardcover/author?author=${encodeURIComponent(this.hardcoverAuthor)}&limit=30`);
                            data = await response.json();
                            if (data.books) {
                                FolioCache.set(cacheKey, data, FolioCache.TTL.HARDCOVER_LIST);
                            }
                        }
                        break;
                    default:
                        // For list IDs
                        if (type.startsWith('list-')) {
                            const listId = type.replace('list-', '');
                            cacheKey = `bookshelf_list_${listId}_30`;
                            data = FolioCache.get(cacheKey);
                            if (!data) {
                                const response = await fetch(`/api/hardcover/list?id=${listId}&limit=30`);
                                data = await response.json();
                                if (data.books) {
                                    FolioCache.set(cacheKey, data, FolioCache.TTL.HARDCOVER_LIST);
                                }
                            }
                        }
                }
                
                if (data && data.books) {
                    this.bookshelfBooks = this.matchWithLibrary(data.books);
                    // Set hasMore if we received the full limit (30 books)
                    this.bookshelfHasMore = data.books.length >= 30;
                    if (cacheKey && FolioCache.get(cacheKey)) {
                        console.log(`📦 Cache hit: bookshelf ${type}`);
                    }
                }
            } catch (error) {
                console.error('Failed to load bookshelf:', error);
            }
        },

        /**
         * Load more books for infinite scroll in bookshelf
         */
        async loadMoreBookshelf() {
            if (this.loadingMoreBookshelf || !this.bookshelfHasMore) return;

            this.loadingMoreBookshelf = true;
            const offset = this.bookshelfBooks.length;
            const limit = 30;

            try {
                let data;
                const type = this.bookshelfType;

                switch (type) {
                    case 'library':
                        // Load more from local library
                        const moreBooks = this.sortedBooks.slice(offset, offset + limit);
                        this.bookshelfBooks = [...this.bookshelfBooks, ...moreBooks];
                        this.bookshelfHasMore = offset + limit < this.sortedBooks.length;
                        break;
                    case 'trending':
                    case 'trending-month':
                        const trendingResponse = await fetch(`/api/hardcover/trending?limit=${limit}&offset=${offset}`);
                        data = await trendingResponse.json();
                        break;
                    case 'recent':
                        const recentResponse = await fetch(`/api/hardcover/recent?limit=${limit}&offset=${offset}`);
                        data = await recentResponse.json();
                        break;
                    default:
                        if (type.startsWith('list-')) {
                            const listId = type.replace('list-', '');
                            const listResponse = await fetch(`/api/hardcover/list?id=${listId}&limit=${limit}&offset=${offset}`);
                            data = await listResponse.json();
                        }
                }

                if (data && data.books) {
                    const matchedBooks = this.matchWithLibrary(data.books);
                    this.bookshelfBooks = [...this.bookshelfBooks, ...matchedBooks];
                    this.bookshelfHasMore = data.books.length >= limit;
                }
            } catch (error) {
                console.error('Failed to load more bookshelf books:', error);
            } finally {
                this.loadingMoreBookshelf = false;
            }
        },

        /**
         * Open bookshelf showing only Reading List books
         */
        openReadingList() {
            this.bookshelfTitle = 'Reading List';
            // Ensure we have latest reading list IDs
            this.loadReadingList().then(() => {
                this.bookshelfBooks = this.sortedBooks.filter(book =>
                    this.isInReadingList(book.id)
                );
                this.navigateToBookshelf('Reading List');
                this.pushHistoryState('bookshelf', { title: 'Reading List' });
            }).catch(() => {
                // Fallback: use current ids even if reload fails
                this.bookshelfBooks = this.sortedBooks.filter(book =>
                    this.isInReadingList(book.id)
                );
                this.navigateToBookshelf('Reading List');
                this.pushHistoryState('bookshelf', { title: 'Reading List' });
            });
        },

        /**
         * Open requests view showing all requested books
         */
        async openRequests() {
            await this.loadRequestedBooks();
            this.navigateToRequests();
            this.pushHistoryState('requests');
        },

        /**
         * Close requests view (navigate back)
         */
        closeRequests() {
            this.selectedRequestBook = null;
            this.prowlarrSearchResults = [];
            // Clear download states
            this.downloadingProwlarr = null;
            this.downloadProwlarrSuccess = null;
            this.downloadProwlarrError = null;
            // Use browser back to return to previous view
            history.back();
        },
        
        /**
         * Search Prowlarr for a requested book
         */
        async searchProwlarr(book) {
            this.selectedRequestBook = book;
            this.prowlarrSearchResults = [];
            this.prowlarrError = null;
            // Clear previous download states
            this.downloadingProwlarr = null;
            this.downloadProwlarrSuccess = null;
            this.downloadProwlarrError = null;
            this.searchingProwlarr = true;
            
            try {
                const query = encodeURIComponent(book.title);
                const author = encodeURIComponent(book.author || '');
                const url = `/api/prowlarr/search?q=${query}${author ? `&author=${author}` : ''}`;
                
                const response = await fetch(url);
                const data = await response.json();
                
                if (data.success) {
                    this.prowlarrSearchResults = data.results || [];
                    this.sortProwlarrResults();
                } else {
                    this.prowlarrError = data.error || 'Failed to search Prowlarr';
                }
            } catch (error) {
                console.error('Failed to search Prowlarr:', error);
                this.prowlarrError = 'Failed to search Prowlarr. Please check your configuration.';
            } finally {
                this.searchingProwlarr = false;
            }
        },
        
        /**
         * Sort Prowlarr search results
         */
        sortProwlarrResults() {
            if (!this.prowlarrSearchResults || this.prowlarrSearchResults.length === 0) return;
            
            const sortBy = this.prowlarrSortBy;
            const order = this.prowlarrSortOrder;
            
            this.prowlarrSearchResults.sort((a, b) => {
                let aVal, bVal;
                
                switch (sortBy) {
                    case 'seeders':
                        aVal = a.seeders || 0;
                        bVal = b.seeders || 0;
                        break;
                    case 'size':
                        aVal = a.size || 0;
                        bVal = b.size || 0;
                        break;
                    case 'title':
                        aVal = (a.title || '').toLowerCase();
                        bVal = (b.title || '').toLowerCase();
                        break;
                    default:
                        return 0;
                }
                
                if (sortBy === 'title') {
                    // String comparison
                    if (order === 'asc') {
                        return aVal.localeCompare(bVal);
                    } else {
                        return bVal.localeCompare(aVal);
                    }
                } else {
                    // Numeric comparison
                    if (order === 'asc') {
                        return aVal - bVal;
                    } else {
                        return bVal - aVal;
                    }
                }
            });
        },
        
        /**
         * Change Prowlarr sort option
         */
        changeProwlarrSort(sortBy) {
            if (this.prowlarrSortBy === sortBy) {
                // Toggle order if same sort field
                this.prowlarrSortOrder = this.prowlarrSortOrder === 'asc' ? 'desc' : 'asc';
            } else {
                // New sort field, default to desc for numeric, asc for title
                this.prowlarrSortBy = sortBy;
                this.prowlarrSortOrder = sortBy === 'title' ? 'asc' : 'desc';
            }
            this.sortProwlarrResults();
        },

        /**
         * Format file size
         */
        formatFileSize(bytes) {
            if (!bytes) return 'Unknown';
            const sizes = ['B', 'KB', 'MB', 'GB'];
            const i = Math.floor(Math.log(bytes) / Math.log(1024));
            return Math.round(bytes / Math.pow(1024, i) * 100) / 100 + ' ' + sizes[i];
        },

        /**
         * Format date from timestamp
         */
        formatRequestDate(timestamp) {
            if (!timestamp) return 'Unknown date';
            const date = new Date(timestamp * 1000);
            return date.toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' });
        },

        /**
         * Get the current section title based on view state
         */
        getSectionTitle() {
            if (this.searchQuery && this.searchQuery.trim()) {
                return 'Search Results';
            }
            if (this.showRequests) {
                return 'Book Requests';
            }
            if (this.showBookshelf) {
                return this.bookshelfTitle || 'Books';
            }
            return 'Your Library';
        },

        /**
         * Check if back button should be shown
         */
        showBackButton() {
            return this.showRequests || this.showBookshelf;
        },

        /**
         * Handle back button click
         */
        handleBackButton() {
            if (this.showRequests) {
                this.closeRequests();
            } else if (this.showBookshelf) {
                this.closeBookshelf();
            }
        },

        /**
         * Format authors array, handling duplicates and various formats
         * Assumes authors are already normalized to "FirstName LastName" from server
         */
        formatAuthors(authors) {
            if (!authors) return 'Unknown Author';
            if (typeof authors === 'string') {
                // If it's a string, try to parse it
                authors = authors.split(' & ').map(a => a.trim()).filter(a => a);
            }
            if (!Array.isArray(authors) || authors.length === 0) {
                return 'Unknown Author';
            }
            
            // Deduplicate and clean up authors
            const seen = new Set();
            const cleaned = [];
            
            for (let author of authors) {
                if (typeof author !== 'string') continue;
                author = author.trim();
                if (!author) continue;
                
                // Server should already normalize, but handle edge cases
                // Normalize: handle "LastName, FirstName" or "LastName| FirstName" format if still present
                let normalized = author;
                if (author.includes(', ')) {
                    const parts = author.split(', ', 2);
                    if (parts.length === 2) {
                        normalized = `${parts[1].trim()} ${parts[0].trim()}`;
                    }
                } else if (author.includes('|')) {
                    const parts = author.split('|', 2);
                    if (parts.length === 2) {
                        normalized = `${parts[1].trim()} ${parts[0].trim()}`;
                    }
                }
                
                normalized = normalized.trim();
                const key = normalized.toLowerCase();
                
                if (normalized && !seen.has(key)) {
                    seen.add(key);
                    cleaned.push(normalized);
                }
            }
            
            return cleaned.length > 0 ? cleaned.join(', ') : 'Unknown Author';
        },

        /**
         * Get last name from author string for sorting purposes
         */
        getLastNameForSort(authorStr) {
            if (!authorStr || authorStr === 'Unknown Author') return '';
            // Get last word (last name) from "FirstName LastName" format
            const parts = authorStr.trim().split(/\s+/);
            if (parts.length >= 2) {
                return parts[parts.length - 1]; // Last word is last name
            }
            return authorStr; // Fallback to full name if single word
        },

        /**
         * Get paginated list books for current page
         */
        paginatedListBooks() {
            if (this.libraryView !== 'list') return this.sortedBooks;
            const start = (this.currentListPage - 1) * this.booksPerPage;
            const end = start + this.booksPerPage;
            return this.sortedBooks.slice(start, end);
        },

        /**
         * Get total pages for list view
         */
        totalListPages() {
            return Math.ceil(this.sortedBooks.length / this.booksPerPage);
        },

        /**
         * Get paginated bookshelf books for current page
         */
        paginatedBookshelfBooks() {
            if (this.bookshelfView !== 'list') return this.bookshelfBooks;
            const start = (this.currentListPage - 1) * this.booksPerPage;
            const end = start + this.booksPerPage;
            return this.bookshelfBooks.slice(start, end);
        },

        /**
         * Get total pages for bookshelf list view
         */
        totalBookshelfPages() {
            if (this.bookshelfView !== 'list') return 1;
            return Math.ceil(this.bookshelfBooks.length / this.booksPerPage);
        },

        /**
         * Go to next page in list view
         */
        nextListPage() {
            if (this.showBookshelf) {
                if (this.currentListPage < this.totalBookshelfPages()) {
                    this.currentListPage++;
                }
            } else {
                if (this.currentListPage < this.totalListPages()) {
                    this.currentListPage++;
                }
            }
        },

        /**
         * Go to previous page in list view
         */
        prevListPage() {
            if (this.currentListPage > 1) {
                this.currentListPage--;
            }
        },

        /**
         * Sort bookshelf books based on bookshelfSortBy
         */
        sortBookshelf() {
            let sorted = [...this.bookshelfBooks];

            switch (this.bookshelfSortBy) {
                case 'recent':
                    // Sort by timestamp, newest first
                    sorted.sort((a, b) => {
                        const dateA = a.timestamp ? new Date(a.timestamp) : new Date(0);
                        const dateB = b.timestamp ? new Date(b.timestamp) : new Date(0);
                        return dateB - dateA;
                    });
                    break;
                case 'title':
                    sorted.sort((a, b) => (a.title || '').localeCompare(b.title || ''));
                    break;
                case 'title-desc':
                    sorted.sort((a, b) => (b.title || '').localeCompare(a.title || ''));
                    break;
                case 'author':
                    sorted.sort((a, b) => {
                        const authorA = a.authors ? this.formatAuthors(a.authors) : (a.author || '');
                        const authorB = b.authors ? this.formatAuthors(b.authors) : (b.author || '');
                        const lastNameA = this.getLastNameForSort(authorA);
                        const lastNameB = this.getLastNameForSort(authorB);
                        return lastNameA.localeCompare(lastNameB);
                    });
                    break;
                case 'author-desc':
                    sorted.sort((a, b) => {
                        const authorA = a.authors ? this.formatAuthors(a.authors) : (a.author || '');
                        const authorB = b.authors ? this.formatAuthors(b.authors) : (b.author || '');
                        const lastNameA = this.getLastNameForSort(authorA);
                        const lastNameB = this.getLastNameForSort(authorB);
                        return lastNameB.localeCompare(lastNameA);
                    });
                    break;
            }

            this.bookshelfBooks = sorted;
            this.currentListPage = 1; // Reset to first page
        },

        /**
         * Close bookshelf view
         */
        closeBookshelf() {
            this.showBookshelf = false;
            this.bookshelfTitle = '';
            this.bookshelfBooks = [];
            this.bookshelfType = '';
            this.bookshelfHasMore = false;
            this.loadingMoreBookshelf = false;
            this.bookshelfSortBy = 'recent';
            this.currentListPage = 1; // Reset pagination
        },

        // ============================================
        // Selection Mode & Bulk Operations
        // ============================================

        /**
         * Toggle selection mode
         */
        toggleSelectionMode() {
            this.selectionMode = !this.selectionMode;
            if (!this.selectionMode) {
                // Clear selection when exiting selection mode
                this.selectedBookIds = [];
            }
        },

        /**
         * Toggle book selection
         */
        toggleBookSelection(bookId) {
            const index = this.selectedBookIds.indexOf(bookId);
            if (index === -1) {
                this.selectedBookIds.push(bookId);
            } else {
                this.selectedBookIds.splice(index, 1);
            }
        },

        /**
         * Check if book is selected
         */
        isBookSelected(bookId) {
            return this.selectedBookIds.includes(bookId);
        },

        /**
         * Select all books on current page
         */
        selectAllOnPage() {
            const booksToSelect = this.libraryView === 'list' 
                ? this.paginatedListBooks()
                : (this.libraryPages[this.currentPage] || []);
            
            booksToSelect.forEach(book => {
                if (!this.selectedBookIds.includes(book.id)) {
                    this.selectedBookIds.push(book.id);
                }
            });
        },

        /**
         * Deselect all books
         */
        deselectAll() {
            this.selectedBookIds = [];
        },

        /**
         * Bulk delete selected books
         */
        async bulkDeleteBooks() {
            if (this.selectedBookIds.length === 0) {
                alert('Please select at least one book to delete.');
                return;
            }

            const confirmed = confirm(`Are you sure you want to delete ${this.selectedBookIds.length} book(s) from your library? This action cannot be undone.`);
            if (!confirmed) {
                return;
            }

            this.bulkActionLoading = true;

            try {
                const response = await fetch('/api/books/bulk-delete', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ book_ids: this.selectedBookIds }),
                });

                const data = await response.json();

                if (data.success) {
                    console.log(`✅ Deleted ${this.selectedBookIds.length} book(s)`);
                    
                    // Remove deleted books from the books array
                    this.books = this.books.filter(book => !this.selectedBookIds.includes(book.id));
                    
                    // Clear selection and exit selection mode
                    this.selectedBookIds = [];
                    this.selectionMode = false;
                    
                    // Re-sort and re-paginate
                    this.sortBooks();
                    
                    // Show success message
                    alert(`Successfully deleted ${data.deleted_count} book(s) from your library.`);
                } else {
                    alert('Failed to delete books: ' + (data.error || 'Unknown error'));
                }
            } catch (error) {
                console.error('Failed to delete books:', error);
                alert('Error deleting books: ' + error.message);
            } finally {
                this.bulkActionLoading = false;
            }
        },

        /**
         * Bulk add selected books to reading list
         */
        async bulkAddToReadingList() {
            if (this.selectedBookIds.length === 0) {
                alert('Please select at least one book to add to reading list.');
                return;
            }

            this.bulkActionLoading = true;

            try {
                const response = await fetch('/api/reading-list/bulk-add', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ book_ids: this.selectedBookIds }),
                });

                const data = await response.json();

                if (data.success) {
                    console.log(`✅ Added ${this.selectedBookIds.length} book(s) to reading list`);
                    
                    // Update reading list IDs
                    if (Array.isArray(data.ids)) {
                        this.readingListIds = [...data.ids];
                    }
                    
                    // Clear selection and exit selection mode
                    this.selectedBookIds = [];
                    this.selectionMode = false;
                    
                    // Show success message
                    alert(`Successfully added ${data.added_count} book(s) to your reading list.`);
                } else {
                    alert('Failed to add books to reading list: ' + (data.error || 'Unknown error'));
                }
            } catch (error) {
                console.error('Failed to add books to reading list:', error);
                alert('Error adding books to reading list: ' + error.message);
            } finally {
                this.bulkActionLoading = false;
            }
        },

        // ============================================
        // Camera Capture Methods
        // ============================================

        /**
         * Open camera capture modal
         */
        async openCameraCapture() {
            console.log('📷 Opening camera capture...');
            this.showCameraCapture = true;
            this.cameraState = 'initializing';
            this.cameraError = '';
            this.capturedImageSrc = '';
            this.lockBodyScroll();

            // Increment request ID to track this specific request
            // This allows us to detect if the modal was closed while getUserMedia was pending
            const requestId = ++this.cameraRequestId;

            // Request camera access
            try {
                const constraints = {
                    video: {
                        facingMode: 'environment', // Prefer rear camera
                        width: { ideal: 1280 },
                        height: { ideal: 720 }
                    }
                };

                const stream = await navigator.mediaDevices.getUserMedia(constraints);

                // Check if modal was closed while waiting for camera permission
                // If so, immediately stop the stream and don't proceed
                if (requestId !== this.cameraRequestId || !this.showCameraCapture) {
                    console.log('📷 Modal closed while waiting for camera, stopping stream');
                    stream.getTracks().forEach(track => track.stop());
                    return;
                }

                this.cameraStream = stream;

                // Wait for video element to be available
                await this.$nextTick();

                // Check again after nextTick in case modal was closed
                if (requestId !== this.cameraRequestId || !this.showCameraCapture) {
                    console.log('📷 Modal closed after camera ready, stopping stream');
                    stream.getTracks().forEach(track => track.stop());
                    this.cameraStream = null;
                    return;
                }

                const video = this.$refs.cameraVideo;
                if (video) {
                    video.srcObject = stream;
                    video.onloadedmetadata = () => {
                        // Final check before setting ready state
                        if (requestId === this.cameraRequestId && this.showCameraCapture) {
                            this.cameraState = 'ready';
                            console.log('📷 Camera ready');
                        }
                    };
                } else {
                    throw new Error('Video element not found');
                }
            } catch (error) {
                // Only show error if this request is still current
                if (requestId !== this.cameraRequestId || !this.showCameraCapture) {
                    return;
                }

                console.error('📷 Camera error:', error);
                this.cameraState = 'error';

                if (error.name === 'NotAllowedError') {
                    this.cameraError = 'Camera access denied. Please allow camera access in your browser settings.';
                } else if (error.name === 'NotFoundError') {
                    this.cameraError = 'No camera found on this device.';
                } else if (error.name === 'NotReadableError') {
                    this.cameraError = 'Camera is in use by another application.';
                } else {
                    this.cameraError = error.message || 'Failed to access camera.';
                }
            }
        },

        /**
         * Close camera capture modal and cleanup
         */
        closeCameraCapture() {
            console.log('📷 Closing camera capture');

            // Increment request ID to invalidate any pending camera requests
            this.cameraRequestId++;

            this.showCameraCapture = false;
            this.cameraState = 'initializing';
            this.capturedImageSrc = '';
            this.unlockBodyScroll();

            // Stop camera stream
            if (this.cameraStream) {
                this.cameraStream.getTracks().forEach(track => track.stop());
                this.cameraStream = null;
            }

            // Clear video source
            const video = this.$refs.cameraVideo;
            if (video) {
                video.srcObject = null;
            }
        },

        /**
         * Capture photo from camera
         */
        capturePhoto() {
            console.log('📷 Capturing photo...');
            const video = this.$refs.cameraVideo;
            const canvas = this.$refs.cameraCanvas;

            if (!video || !canvas) {
                console.error('📷 Video or canvas element not found');
                return;
            }

            // Set canvas dimensions to video dimensions
            canvas.width = video.videoWidth;
            canvas.height = video.videoHeight;

            // Draw video frame to canvas
            const ctx = canvas.getContext('2d');
            ctx.drawImage(video, 0, 0);

            // Export as JPEG at 0.8 quality
            const imageDataUrl = canvas.toDataURL('image/jpeg', 0.8);
            this.capturedImageSrc = imageDataUrl;
            this.cameraState = 'captured';

            // Stop camera stream to save resources
            if (this.cameraStream) {
                this.cameraStream.getTracks().forEach(track => track.stop());
                this.cameraStream = null;
            }

            console.log('📷 Photo captured');
        },

        /**
         * Retake photo - restart camera
         */
        async retakePhoto() {
            console.log('📷 Retaking photo...');
            this.capturedImageSrc = '';
            this.cameraState = 'initializing';

            // Restart camera
            await this.openCameraCapture();
        },

        /**
         * Send captured image to backend for identification
         */
        async identifyBook() {
            if (!this.capturedImageSrc) {
                console.error('📷 No captured image');
                return;
            }

            console.log('📷 Identifying book from image...');
            this.cameraState = 'identifying';

            try {
                const response = await fetch('/api/camera/identify', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ image: this.capturedImageSrc })
                });

                const data = await response.json();

                if (data.success) {
                    console.log('📷 Book identified:', data.identified);

                    // Close camera modal
                    this.closeCameraCapture();

                    // Set the search query to the identified title/author
                    this.searchQuery = data.search_query || `${data.identified.title} ${data.identified.author}`.trim();

                    // Display the search results directly (bypass normal search)
                    this.filteredBooks = [];
                    this.searchiTunesResults = this.matchWithLibrary(data.books || []);
                    this.searchiTunesPage = 1;
                    this.searchiTunesHasMore = false; // Results already complete from backend
                    this.loadingSearchiTunes = false;

                    // Scroll to top to see results
                    window.scrollTo({ top: 0, behavior: 'smooth' });

                    console.log(`📷 Found ${this.searchiTunesResults.length} books for "${this.searchQuery}"`);
                } else {
                    // Identification failed
                    console.error('📷 Identification failed:', data.error);
                    this.closeCameraCapture();

                    // Focus the search input and show a message
                    alert(`Couldn't identify the book. ${data.error || 'Try again or search manually.'}`);

                    // Focus the search input
                    await this.$nextTick();
                    if (this.$refs.searchInput) {
                        this.$refs.searchInput.focus();
                    }
                }
            } catch (error) {
                console.error('📷 Identification request failed:', error);
                this.cameraState = 'captured';
                alert('Failed to identify book. Please try again or search manually.');
            }
        },
    };
}
