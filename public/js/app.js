/**
 * Folio - Main Application
 */

function folioApp() {
    return {
        // State
        currentTab: 'library',
        books: [],
        filteredBooks: [],
        selectedBook: null,
        searchQuery: '',
        loading: false,
        showSettings: false,

        // Configuration
        calibreUrl: localStorage.getItem('calibreUrl') || 'http://localhost:8080',
        pocketbaseUrl: localStorage.getItem('pocketbaseUrl') || 'http://localhost:8090',

        // API Clients
        calibreAPI: null,
        db: null,

        /**
         * Initialize the application
         */
        async init() {
            console.log('Initializing Folio...');

            // Initialize API clients
            this.calibreAPI = new CalibreAPI(this.calibreUrl);
            this.db = new FolioDatabase(this.pocketbaseUrl);
            await this.db.init();

            // Test connections
            const calibreOk = await this.calibreAPI.testConnection();
            const pocketbaseOk = await this.db.testConnection();

            if (!calibreOk) {
                console.warn('⚠️ Cannot connect to Calibre Content Server. Check settings.');
            }

            if (!pocketbaseOk) {
                console.warn('⚠️ Cannot connect to PocketBase. Check settings.');
            }

            // Load initial data
            if (calibreOk) {
                await this.loadBooks();
            }

            console.log('✅ Folio initialized');
        },

        /**
         * Load books from Calibre Content Server
         */
        async loadBooks() {
            this.loading = true;
            try {
                this.books = await this.calibreAPI.getBooks({ limit: 100 });
                this.filteredBooks = this.books;
                console.log(`Loaded ${this.books.length} books`);
            } catch (error) {
                console.error('Failed to load books:', error);
                this.books = [];
                this.filteredBooks = [];
            } finally {
                this.loading = false;
            }
        },

        /**
         * Search books
         */
        async searchBooks() {
            if (!this.searchQuery.trim()) {
                this.filteredBooks = this.books;
                return;
            }

            this.loading = true;
            try {
                // Local search first (faster)
                const query = this.searchQuery.toLowerCase();
                this.filteredBooks = this.books.filter(book => {
                    return (
                        book.title?.toLowerCase().includes(query) ||
                        book.authors?.toLowerCase().includes(query) ||
                        book.tags?.some(tag => tag.toLowerCase().includes(query))
                    );
                });

                // If no local results, try server search
                if (this.filteredBooks.length === 0) {
                    this.filteredBooks = await this.calibreAPI.searchBooks(this.searchQuery);
                }
            } catch (error) {
                console.error('Search failed:', error);
            } finally {
                this.loading = false;
            }
        },

        /**
         * Open book detail modal
         */
        async openBookModal(book) {
            this.selectedBook = book;

            // Load full metadata in background
            try {
                const fullMetadata = await this.calibreAPI.getBookMetadata(book.id);
                this.selectedBook = { ...this.selectedBook, ...fullMetadata };
            } catch (error) {
                console.error('Failed to load book metadata:', error);
            }
        },

        /**
         * Save settings
         */
        saveSettings() {
            localStorage.setItem('calibreUrl', this.calibreUrl);
            localStorage.setItem('pocketbaseUrl', this.pocketbaseUrl);

            // Reinitialize API clients
            this.calibreAPI = new CalibreAPI(this.calibreUrl);
            this.db = new FolioDatabase(this.pocketbaseUrl);

            // Reload data
            this.loadBooks();

            console.log('Settings saved');
        },

        /**
         * Format authors array or string
         */
        formatAuthors(authors) {
            if (Array.isArray(authors)) {
                return authors.join(', ');
            }
            return authors || 'Unknown Author';
        },
    };
}
