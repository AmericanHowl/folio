/**
 * Folio - Main Application
 * Simple static app that talks to Calibre Content Server
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

        // Configuration (stored in localStorage)
        calibreUrl: localStorage.getItem('calibreUrl') || '/api',

        // API Client
        calibreAPI: null,

        /**
         * Initialize the application
         */
        async init() {
            console.log('📚 Initializing Folio...');

            this.calibreAPI = new CalibreAPI(this.calibreUrl);

            // Test connection
            const connected = await this.calibreAPI.testConnection();

            if (!connected) {
                console.warn('⚠️ Cannot connect to Calibre Content Server');
                console.log('💡 Make sure Calibre Content Server is running');
                console.log(`   calibre-server --port 8080 "/path/to/library"`);
                return;
            }

            // Load books
            await this.loadBooks();

            console.log('✅ Folio ready!');
        },

        /**
         * Load books from Calibre Content Server
         */
        async loadBooks() {
            this.loading = true;
            try {
                this.books = await this.calibreAPI.getBooks({ limit: 100 });
                this.filteredBooks = this.books;
                console.log(`📖 Loaded ${this.books.length} books`);
            } catch (error) {
                console.error('Failed to load books:', error);
                this.books = [];
                this.filteredBooks = [];
            } finally {
                this.loading = false;
            }
        },

        /**
         * Search books (client-side first, then server if needed)
         */
        async searchBooks() {
            const query = this.searchQuery.toLowerCase().trim();

            if (!query) {
                this.filteredBooks = this.books;
                return;
            }

            // Client-side search first (instant!)
            this.filteredBooks = this.books.filter(book => {
                return (
                    book.title?.toLowerCase().includes(query) ||
                    book.authors?.toLowerCase().includes(query) ||
                    book.tags?.some(tag => tag.toLowerCase().includes(query))
                );
            });

            // If no results, try server search
            if (this.filteredBooks.length === 0) {
                this.loading = true;
                try {
                    this.filteredBooks = await this.calibreAPI.searchBooks(this.searchQuery);
                } catch (error) {
                    console.error('Search failed:', error);
                } finally {
                    this.loading = false;
                }
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
         * Save settings to localStorage
         */
        saveSettings() {
            localStorage.setItem('calibreUrl', this.calibreUrl);
            this.calibreAPI = new CalibreAPI(this.calibreUrl);
            this.loadBooks();
            console.log('✅ Settings saved');
        },
    };
}
