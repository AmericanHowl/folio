/**
 * Folio - Main Application
 * Modern book library interface with Hardcover.app integration
 */

function folioApp() {
    return {
        // Setup state
        showSetup: true,
        setupStep: 1, // 1 = Hardcover API, 2 = Calibre Library
        
        // Library state
        books: [],
        filteredBooks: [],
        displayedBooks: [],
        selectedBook: null,
        searchQuery: '',
        loading: false,
        currentTab: 'library',
        
        // Configuration
        calibreLibraryPath: '',
        hardcoverToken: false,
        
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
        hardcoverRecentReleases: [],
        hardcoverSections: [],
        hardcoverAuthorBooks: [],
        hardcoverAuthor: '',
        selectedHardcoverBook: null,
        
        // Requests
        requestedBooks: [],
        
        // Settings
        showSettings: false,
        
        /**
         * Initialize the application
         */
        async init() {
            console.log('📚 Initializing Folio...');
            
            // Load server config
            await this.loadConfig();
            
            // Check if setup is needed
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
            
            // Setup complete, load the app
            this.showSetup = false;
            await this.loadApp();
        },
        
        /**
         * Load the main application data
         */
        async loadApp() {
            this.loading = true;
            
            try {
                // Load local library and Hardcover data in parallel
                await Promise.all([
                    this.loadBooks(),
                    this.loadRequestedBooks(),
                ]);
                
                // Load Hardcover data after we have books (for matching)
                await this.loadHardcoverData();
                
                console.log('✅ Folio ready!');
            } catch (error) {
                console.error('Failed to load app:', error);
            } finally {
                this.loading = false;
            }
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
                
                // Re-initialize Lucide icons for new content
                if (typeof lucide !== 'undefined') {
                    setTimeout(() => lucide.createIcons(), 0);
                }
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
                
                // Hide setup and load app
                this.showSetup = false;
                await this.loadApp();
                
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
                const response = await fetch('/api/books?limit=100&offset=0');
                this.books = await response.json();
                this.filteredBooks = this.books;
                console.log(`📖 Loaded ${this.books.length} books from library`);
            } catch (error) {
                console.error('Failed to load books:', error);
                this.books = [];
                this.filteredBooks = [];
            }
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
         * Search books (client-side)
         */
        searchBooks() {
            const query = this.searchQuery.toLowerCase().trim();
            
            if (!query) {
                this.filteredBooks = this.books;
                return;
            }
            
            this.filteredBooks = this.books.filter(book => {
                const authorsText = Array.isArray(book.authors)
                    ? book.authors.join(' ').toLowerCase()
                    : (book.authors?.toLowerCase() || '');
                
                return (
                    book.title?.toLowerCase().includes(query) ||
                    authorsText.includes(query) ||
                    book.tags?.some(tag => tag.toLowerCase().includes(query))
                );
            });
        },
        
        /**
         * Get recently added books
         */
        getRecentBooks() {
            return [...this.books]
                .sort((a, b) => {
                    const dateA = a.timestamp ? new Date(a.timestamp) : new Date(0);
                    const dateB = b.timestamp ? new Date(b.timestamp) : new Date(0);
                    return dateB - dateA;
                })
                .slice(0, 20);
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
                    this.loadHardcoverRecent(),
                    this.loadHardcoverLists(),
                    this.loadHardcoverAuthorBooks()
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
            try {
                const response = await fetch('/api/hardcover/lists');
                const data = await response.json();
                
                if (data.error || !data.lists || data.lists.length === 0) {
                    console.error('Lists error:', data.error);
                    this.hardcoverSections = [];
                    return;
                }
                
                // Randomly select 2 lists
                const shuffled = data.lists.sort(() => 0.5 - Math.random());
                const selectedLists = shuffled.slice(0, 2);
                
                // Load books from selected lists
                const listPromises = selectedLists.map(list => this.loadHardcoverList(list.id));
                const results = await Promise.all(listPromises);
                
                this.hardcoverSections = results.filter(result => result.books.length > 0);
                console.log(`📚 Loaded ${this.hardcoverSections.length} curated lists`);
            } catch (error) {
                console.error('Failed to load lists:', error);
                this.hardcoverSections = [];
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
                    return { books: [], name: '', description: '' };
                }
                
                return {
                    books: this.matchWithLibrary(data.books || []),
                    name: data.list_name || '',
                    description: data.list_description || ''
                };
            } catch (error) {
                console.error(`Failed to load list ${listId}:`, error);
                return { books: [], name: '', description: '' };
            }
        },
        
        /**
         * Load books by a random author from local library
         */
        async loadHardcoverAuthorBooks() {
            try {
                const authors = this.getTopAuthors();
                if (!authors || authors.length === 0) {
                    this.hardcoverAuthorBooks = [];
                    this.hardcoverAuthor = '';
                    return;
                }
                
                // Select a random author
                const randomAuthor = authors[Math.floor(Math.random() * authors.length)];
                this.hardcoverAuthor = randomAuthor;
                
                const response = await fetch(`/api/hardcover/author?author=${encodeURIComponent(randomAuthor)}&limit=20`);
                const data = await response.json();
                
                if (data.error) {
                    console.error(`Author ${randomAuthor} error:`, data.error);
                    this.hardcoverAuthorBooks = [];
                } else {
                    this.hardcoverAuthorBooks = this.matchWithLibrary(data.books || []);
                    console.log(`👤 Loaded ${this.hardcoverAuthorBooks.length} books by ${randomAuthor}`);
                }
            } catch (error) {
                console.error('Failed to load author books:', error);
                this.hardcoverAuthorBooks = [];
                this.hardcoverAuthor = '';
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
            return str
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
                }
            } catch (error) {
                console.error('Failed to request book:', error);
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
    };
}
