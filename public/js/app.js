/**
 * Folio - Main Application
 * Modern book library interface with Hardcover.app integration
 */

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
        bookshelfView: 'list', // 'list' or 'grid' - default to list for bookshelf
        booksPerPage: 10, // Books per page in list view
        currentListPage: 1, // Current page in list view
        libraryLoading: false,
        
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
        // Reading list (IDs of library books)
        readingListIds: [],
        readingListStatus: null, // 'added' | 'remove' | null
        
        // Settings
        showSettings: false,
        
        // Cache-buster for covers
        coverVersion: Date.now(),
        
        // Bookshelf view (for viewing full sections)
        showBookshelf: false,
        bookshelfTitle: '',
        bookshelfBooks: [],

        // Search (iTunes)
        searchiTunesResults: [],
        searchiTunesPage: 0,
        searchiTunesHasMore: false,
        loadingSearchiTunes: false,

        // Back to top
        showBackToTop: false,

        /**
         * Initialize the application
         */
        async init() {
            console.log('📚 Initializing Folio...');
            
            // Calculate books per page based on screen size
            this.calculateBooksPerPage();
            window.addEventListener('resize', () => this.calculateBooksPerPage());

            // Back-to-top visibility and infinite scroll
            window.addEventListener('scroll', () => {
                this.showBackToTop = window.scrollY > 400;
                
                // Infinite scroll for search results
                if (this.searchQuery && this.searchQuery.trim() && !this.loadingSearchiTunes && this.searchiTunesHasMore) {
                    const scrollPosition = window.innerHeight + window.scrollY;
                    const documentHeight = document.documentElement.scrollHeight;
                    // Load more when within 200px of bottom
                    if (scrollPosition >= documentHeight - 200) {
                        this.loadMoreiTunesSearch();
                    }
                }
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
                // Load local library first (priority)
                await this.loadBooks();
            await this.loadRequestedBooks();
                await this.loadReadingList();

                this.libraryLoading = false;

                // Load Hardcover data asynchronously (not blocking)
                this.loadHardcoverData();

            console.log('✅ Folio ready!');
            } catch (error) {
                console.error('Failed to load app:', error);
                this.libraryLoading = false;
            }

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
                console.log('📖 Loaded config:', { 
                    library: this.calibreLibraryPath ? 'Set' : 'Not set',
                    token: this.hardcoverToken ? 'Set' : 'Not set'
                });
            } catch (error) {
                console.error('Failed to load config:', error);
            }
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

                // Test connection by checking Prowlarr system status
                // Use the config endpoint which should work with valid API key
                const prowlarrUrl = this.prowlarrUrlInput.trim().replace(/\/+$/, '');
                const testUrl = prowlarrUrl + '/api/v1/system/status';
                const testReq = new Request(testUrl, {
                    headers: {
                        'X-Api-Key': this.prowlarrApiKeyInput.trim()
                    }
                });
                
                try {
                    const testResponse = await fetch(testReq);
                    if (!testResponse.ok) {
                        if (testResponse.status === 401) {
                            this.prowlarrError = 'Invalid API key. Please check your Prowlarr API key.';
                        } else {
                            this.prowlarrError = `Failed to connect to Prowlarr (HTTP ${testResponse.status}). Please check your URL.`;
                        }
                        return;
                }
            } catch (error) {
                    this.prowlarrError = 'Failed to connect to Prowlarr. Please check your URL and API key.';
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
         * Download from Prowlarr and add to Calibre
         */
        async downloadFromProwlarr(result, book) {
            // TODO: Implement download and add to Calibre
            alert('Download functionality will be implemented next. This will download the file and add it to your Calibre library.');
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
         */
        async loadBooks() {
            try {
                const response = await fetch('/api/books?limit=500&offset=0');
                this.books = await response.json();
                this.sortBooks();
                console.log(`📖 Loaded ${this.books.length} books from library`);
            } catch (error) {
                console.error('Failed to load books:', error);
                this.books = [];
                this.sortedBooks = [];
                this.filteredBooks = [];
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
                        return authorA.localeCompare(authorB);
                    });
                    break;
                case 'author-desc':
                    sorted.sort((a, b) => {
                        const authorA = this.formatAuthors(a.authors);
                        const authorB = this.formatAuthors(b.authors);
                        return authorB.localeCompare(authorA);
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
            this.selectedBook = book;
            this.selectedHardcoverBook = null;
            
            // Check if book is already in reading list and set status accordingly
            if (this.isInReadingList(book.id)) {
                this.readingListStatus = 'remove';
                } else {
                this.readingListStatus = null;
            }
            
            // Check for iTunes match
            this.checkiTunesMatch(book);
        },

        /**
         * Check if local book has an iTunes match
         */
        async checkiTunesMatch(book) {
            this.selectedBookiTunesMatch = null;
            
            try {
                const title = book.title;
                const author = Array.isArray(book.authors) ? book.authors[0] : book.authors;
                
                const response = await fetch(`/api/itunes/search?q=${encodeURIComponent(title + ' ' + author)}&limit=5`);
                const data = await response.json();

                if (data.books && data.books.length > 0) {
                    // Find best match
                    for (const itunesBook of data.books) {
                        const titleMatch = this.calculateSimilarity(
                            this.normalizeForMatching(book.title),
                            this.normalizeForMatching(itunesBook.title)
                        );
                        const authorMatch = this.calculateSimilarity(
                            this.normalizeForMatching(author),
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
                    
                    // Reload books to show updated data
                    await this.loadBooks();
                    
                    // Update selected book reference and stay on modal
                    const updatedBook = this.books.find(b => b.id === bookId);
                    if (updatedBook) {
                        this.selectedBook = updatedBook;
                        this.selectedBookiTunesMatch = null;
                    }
                    
                    // Bust cover cache so the new cover shows immediately
                    this.coverVersion = Date.now();
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
        },

        /**
         * Save edited metadata
         */
        async saveEditedMetadata() {
            if (!this.editingBook) return;
            
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
                    
                    // Reload books
                await this.loadBooks();

                    // Update selected book and exit edit mode
                const updatedBook = this.books.find(b => b.id === this.editingBook.id);
                if (updatedBook) {
                    this.selectedBook = updatedBook;
                }

                    // Bust cover cache so the new cover shows immediately
                    this.coverVersion = Date.now();
                    
                    this.exitEditMode();
                } else {
                    alert('Failed to save metadata: ' + (result.errors?.join(', ') || 'Unknown error'));
                }
            } catch (error) {
                console.error('Failed to save metadata:', error);
                alert('Error saving metadata: ' + error.message);
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
         * Load all Hardcover data
         */
        async loadHardcoverData() {
            if (!this.hardcoverToken) return;

            this.hardcoverLoading = true;
            
            try {
                await Promise.all([
                    this.loadHardcoverTrending(),
                    this.loadHardcoverTrendingMonth(),
                    this.loadHardcoverRecent(),
                    this.loadHardcoverLists()
                ]);
                
                console.log('✅ Hardcover data loaded');
            } catch (error) {
                console.error('❌ Failed to load Hardcover data:', error);
            } finally {
                this.hardcoverLoading = false;
            }
        },

        /**
         * Load trending books
         */
        async loadHardcoverTrending() {
            try {
                const response = await fetch('/api/hardcover/trending?limit=20');
                const data = await response.json();

                if (data.error) {
                    console.error('Trending error:', data.error);
                    this.hardcoverTrending = [];
                } else {
                    this.hardcoverTrending = this.matchWithLibrary(data.books || []);
                    console.log(`📈 Loaded ${this.hardcoverTrending.length} trending books`);
                }
            } catch (error) {
                console.error('Failed to load trending:', error);
                this.hardcoverTrending = [];
            }
        },

        /**
         * Load most popular releases from 2025
         */
        async loadHardcoverTrendingMonth() {
            try {
                const response = await fetch('/api/hardcover/trending?limit=20');
                const data = await response.json();

                if (data.error) {
                    console.error('Trending month error:', data.error);
                    this.hardcoverTrendingMonth = [];
                } else {
                    this.hardcoverTrendingMonth = this.matchWithLibrary(data.books || []);
                    console.log(`📈 Loaded ${this.hardcoverTrendingMonth.length} popular 2025 books`);
                }
            } catch (error) {
                console.error('Failed to load trending month:', error);
                this.hardcoverTrendingMonth = [];
            }
        },

        /**
         * Load recent releases
         */
        async loadHardcoverRecent() {
            try {
                const response = await fetch('/api/hardcover/recent?limit=20');
                const data = await response.json();
                
                if (data.error) {
                    console.error('Recent releases error:', data.error);
                    this.hardcoverRecentReleases = [];
                } else {
                    this.hardcoverRecentReleases = this.matchWithLibrary(data.books || []);
                    console.log(`🆕 Loaded ${this.hardcoverRecentReleases.length} recent releases`);
                }
            } catch (error) {
                console.error('Failed to load recent releases:', error);
                this.hardcoverRecentReleases = [];
            }
        },

        /**
         * Load curated lists from @hardcover
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
                
                // Load books from selected lists
                const listPromises = selectedLists.map(list => this.loadHardcoverList(list.id));
                const results = await Promise.all(listPromises);
                
                // Set sections atomically to prevent glitching - only set valid sections with books
                const validSections = results.filter(result => result.books && result.books.length > 0);
                // Set all at once to prevent incremental updates
                this.hardcoverSections = [...validSections];
                console.log(`📚 Loaded ${this.hardcoverSections.length} curated lists`);
            } catch (error) {
                console.error('Failed to load lists:', error);
                this.hardcoverSections = [];
            } finally {
                this.loadingHardcoverLists = false;
            }
        },

        /**
         * Load books from a specific list
         */
        async loadHardcoverList(listId) {
            try {
                const response = await fetch(`/api/hardcover/list?id=${listId}&limit=20`);
                const data = await response.json();

                if (data.error) {
                    return { id: listId, books: [], name: '', description: '' };
                }
                
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
         * Load more iTunes search results (incremental)
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

            try {
                const response = await fetch(`/api/itunes/search?q=${encodeURIComponent(this.searchQuery)}&limit=${pageSize}&offset=${offset}`);
                const data = await response.json();
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
         * Open bookshelf view with a section's books
         */
        async openBookshelf(type, title) {
            this.bookshelfTitle = title;
            this.bookshelfBooks = [];
            this.bookshelfView = 'list'; // Default to list view for bookshelf
            this.currentListPage = 1; // Reset to first page
            this.showBookshelf = true;
            
            // Load 30 books for the bookshelf
            try {
                let response;
                switch (type) {
                    case 'library':
                        this.bookshelfBooks = this.sortedBooks.slice(0, 30);
                        return;
                    case 'library-all':
                        this.bookshelfBooks = this.sortedBooks;
                        return;
                    case 'trending':
                        response = await fetch('/api/hardcover/trending?limit=30');
                        break;
                    case 'trending-month':
                        response = await fetch('/api/hardcover/trending?limit=30');
                        break;
                    case 'recent':
                        response = await fetch('/api/hardcover/recent?limit=30');
                        break;
                    case 'author':
                        response = await fetch(`/api/hardcover/author?author=${encodeURIComponent(this.hardcoverAuthor)}&limit=30`);
                        break;
                    default:
                        // For list IDs
                        if (type.startsWith('list-')) {
                            const listId = type.replace('list-', '');
                            response = await fetch(`/api/hardcover/list?id=${listId}&limit=30`);
                        }
                }
                
                if (response) {
                    const data = await response.json();
                    if (data.books) {
                        this.bookshelfBooks = this.matchWithLibrary(data.books);
                    }
                }
            } catch (error) {
                console.error('Failed to load bookshelf:', error);
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
                this.showBookshelf = true;
            }).catch(() => {
                // Fallback: use current ids even if reload fails
                this.bookshelfBooks = this.sortedBooks.filter(book =>
                    this.isInReadingList(book.id)
                );
                this.showBookshelf = true;
            });
        },

        /**
         * Open requests view showing all requested books
         */
        async openRequests() {
            await this.loadRequestedBooks();
            this.showRequests = true;
        },

        /**
         * Close requests view
         */
        closeRequests() {
            this.showRequests = false;
            this.selectedRequestBook = null;
            this.prowlarrSearchResults = [];
        },
        
        /**
         * Search Prowlarr for a requested book
         */
        async searchProwlarr(book) {
            this.selectedRequestBook = book;
            this.prowlarrSearchResults = [];
            this.prowlarrError = null;
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
         * Format authors array, handling duplicates and various formats
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
                
                // Normalize: handle "LastName, FirstName" or "LastName| FirstName" format
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
         * Close bookshelf view
         */
        closeBookshelf() {
            this.showBookshelf = false;
            this.bookshelfTitle = '';
            this.bookshelfBooks = [];
            this.currentListPage = 1; // Reset pagination
        },
    };
}
