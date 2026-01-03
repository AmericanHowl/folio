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
        displayedBooks: [],
        selectedBook: null,
        searchQuery: '',
        loading: false,
        loadingMore: false,
        showSettings: false,

        // Pagination
        booksPerPage: 30,
        currentPage: 0,
        totalBooks: 0,

        // Sorting
        sortBy: 'title-asc',

        // Auto-update
        autoUpdateInterval: null,
        lastBookCount: 0,
        hasNewBooks: false,

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

            // Start auto-update check
            this.startAutoUpdate();

            console.log('✅ Folio ready!');
        },

        /**
         * Load books from Calibre Content Server
         */
        async loadBooks() {
            this.loading = true;
            this.currentPage = 0;
            try {
                // Load first page
                this.books = await this.calibreAPI.getBooks({
                    limit: this.booksPerPage,
                    offset: 0
                });
                this.filteredBooks = this.books;
                this.totalBooks = this.books.length;
                this.updateDisplayedBooks();
                console.log(`📖 Loaded ${this.books.length} books`);
            } catch (error) {
                console.error('Failed to load books:', error);
                this.books = [];
                this.filteredBooks = [];
                this.displayedBooks = [];
            } finally {
                this.loading = false;
            }
        },

        /**
         * Load more books (pagination)
         */
        async loadMoreBooks() {
            if (this.loadingMore) return;

            this.loadingMore = true;
            try {
                const nextPage = this.currentPage + 1;
                const newBooks = await this.calibreAPI.getBooks({
                    limit: this.booksPerPage,
                    offset: nextPage * this.booksPerPage
                });

                if (newBooks.length > 0) {
                    this.books = [...this.books, ...newBooks];
                    this.filteredBooks = this.books;
                    this.currentPage = nextPage;
                    this.updateDisplayedBooks();
                    console.log(`📖 Loaded ${newBooks.length} more books (total: ${this.books.length})`);
                }
            } catch (error) {
                console.error('Failed to load more books:', error);
            } finally {
                this.loadingMore = false;
            }
        },

        /**
         * Update the list of displayed books
         */
        updateDisplayedBooks() {
            this.displayedBooks = this.sortBooks(this.filteredBooks);
        },

        /**
         * Sort books based on current sort option
         */
        sortBooks(bookList) {
            const sorted = [...bookList];

            switch (this.sortBy) {
                case 'title-asc':
                    sorted.sort((a, b) => (a.title || '').localeCompare(b.title || ''));
                    break;
                case 'title-desc':
                    sorted.sort((a, b) => (b.title || '').localeCompare(a.title || ''));
                    break;
                case 'author-asc':
                    sorted.sort((a, b) => {
                        const authorA = Array.isArray(a.authors) ? a.authors[0] : (a.authors || '');
                        const authorB = Array.isArray(b.authors) ? b.authors[0] : (b.authors || '');
                        return authorA.localeCompare(authorB);
                    });
                    break;
                case 'author-desc':
                    sorted.sort((a, b) => {
                        const authorA = Array.isArray(a.authors) ? a.authors[0] : (a.authors || '');
                        const authorB = Array.isArray(b.authors) ? b.authors[0] : (b.authors || '');
                        return authorB.localeCompare(authorA);
                    });
                    break;
                case 'date-desc':
                    sorted.sort((a, b) => {
                        const dateA = a.pubdate ? new Date(a.pubdate) : new Date(0);
                        const dateB = b.pubdate ? new Date(b.pubdate) : new Date(0);
                        return dateB - dateA;
                    });
                    break;
                case 'date-asc':
                    sorted.sort((a, b) => {
                        const dateA = a.pubdate ? new Date(a.pubdate) : new Date(0);
                        const dateB = b.pubdate ? new Date(b.pubdate) : new Date(0);
                        return dateA - dateB;
                    });
                    break;
            }

            return sorted;
        },

        /**
         * Change sort order
         */
        changeSortOrder(sortBy) {
            this.sortBy = sortBy;
            this.updateDisplayedBooks();
        },

        /**
         * Start auto-update check for new books
         */
        startAutoUpdate() {
            // Check every 30 seconds
            this.autoUpdateInterval = setInterval(() => {
                this.checkForNewBooks();
            }, 30000);
        },

        /**
         * Check if new books have been added
         */
        async checkForNewBooks() {
            try {
                const libraryInfo = await this.calibreAPI.getLibraryMetadata();
                const currentCount = libraryInfo.total_num || 0;

                if (this.lastBookCount === 0) {
                    this.lastBookCount = currentCount;
                    return;
                }

                if (currentCount > this.lastBookCount) {
                    console.log(`🆕 New books detected! (${currentCount - this.lastBookCount} new)`);
                    this.hasNewBooks = true;
                    this.lastBookCount = currentCount;
                }
            } catch (error) {
                console.error('Failed to check for new books:', error);
            }
        },

        /**
         * Refresh library to load new books
         */
        async refreshLibrary() {
            this.hasNewBooks = false;
            await this.loadBooks();
            console.log('📚 Library refreshed');
        },

        /**
         * Search books (client-side first, then server if needed)
         */
        async searchBooks() {
            const query = this.searchQuery.toLowerCase().trim();

            if (!query) {
                this.filteredBooks = this.books;
                this.updateDisplayedBooks();
                return;
            }

            // Client-side search first (instant!)
            this.filteredBooks = this.books.filter(book => {
                // Handle authors as either string or array
                const authorsText = Array.isArray(book.authors)
                    ? book.authors.join(' ').toLowerCase()
                    : (book.authors?.toLowerCase() || '');

                return (
                    book.title?.toLowerCase().includes(query) ||
                    authorsText.includes(query) ||
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

            this.updateDisplayedBooks();
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
