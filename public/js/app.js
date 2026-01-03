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
        showEditMetadata: false,
        showBrowser: false,
        showInitialSetup: false,
        editingBook: null,

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

        // Configuration
        calibreLibraryPath: '',

        // Directory Browser
        browserPath: '',
        browserParent: null,
        browserEntries: [],

        /**
         * Initialize the application
         */
        async init() {
            console.log('📚 Initializing Folio...');

            // Load server config
            await this.loadConfig();

            // Check if we need initial setup
            if (!this.calibreLibraryPath) {
                console.log('📋 No library configured, showing setup screen');
                this.showInitialSetup = true;
                return;
            }

            // Load books
            await this.loadBooks();

            // Start auto-update check
            this.startAutoUpdate();

            console.log('✅ Folio ready!');
        },

        /**
         * Load books from Calibre database
         */
        async loadBooks() {
            this.loading = true;
            this.currentPage = 0;
            try {
                // Load books from API
                const response = await fetch(`/api/books?limit=${this.booksPerPage}&offset=0`);
                this.books = await response.json();
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
                const offset = nextPage * this.booksPerPage;
                const response = await fetch(`/api/books?limit=${this.booksPerPage}&offset=${offset}`);
                const newBooks = await response.json();

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

            this.updateDisplayedBooks();
        },

        /**
         * Open book detail modal
         */
        async openBookModal(book) {
            this.selectedBook = book;
            // Metadata is already complete from database query
        },

        /**
         * Load configuration from server
         */
        async loadConfig() {
            try {
                const response = await fetch('/api/config');
                const data = await response.json();
                this.calibreLibraryPath = data.calibre_library || '';
                console.log('📖 Loaded config:', data);
            } catch (error) {
                console.error('Failed to load config:', error);
            }
        },

        /**
         * Save settings (library path to server)
         */
        async saveSettings() {
            // Save library path to server
            try {
                const response = await fetch('/api/config', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                        calibre_library: this.calibreLibraryPath
                    }),
                });

                const result = await response.json();
                if (result.success) {
                    console.log('✅ Settings saved');
                    this.loadBooks();
                } else {
                    console.error('Failed to save settings:', result.error);
                    alert('Failed to save settings: ' + result.error);
                }
            } catch (error) {
                console.error('Failed to save settings:', error);
                alert('Failed to save settings: ' + error.message);
            }
        },

        /**
         * Open directory browser
         */
        async openBrowser() {
            this.showBrowser = true;
            // Start from home directory or current path
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
                    alert(`Error: ${data.error}`);
                    return;
                }

                this.browserPath = data.path;
                this.browserParent = data.parent;
                this.browserEntries = data.entries;
            } catch (error) {
                console.error('Failed to browse:', error);
                alert('Failed to browse directory: ' + error.message);
            }
        },

        /**
         * Select a library from the browser
         */
        selectLibrary(path) {
            this.calibreLibraryPath = path;
            this.showBrowser = false;
            console.log('📚 Selected library:', path);
        },

        /**
         * Complete initial setup
         */
        async completeSetup() {
            if (!this.calibreLibraryPath) {
                alert('Please select a Calibre library directory');
                return;
            }

            // Save config
            try {
                const response = await fetch('/api/config', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                        calibre_library: this.calibreLibraryPath
                    }),
                });

                const result = await response.json();
                if (result.success) {
                    console.log('✅ Setup complete');
                    this.showInitialSetup = false;
                    // Initialize the app
                    this.init();
                } else {
                    console.error('Failed to save config:', result.error);
                    alert('Failed to save configuration: ' + result.error);
                }
            } catch (error) {
                console.error('Failed to complete setup:', error);
                alert('Failed to complete setup: ' + error.message);
            }
        },

        /**
         * Open edit metadata modal
         */
        openEditMetadata(book) {
            this.editingBook = { ...book };
            this.showEditMetadata = true;
            this.selectedBook = null; // Close book detail modal
        },

        /**
         * Save metadata changes
         */
        async saveMetadata() {
            console.log('📝 Saving metadata for book:', this.editingBook);

            this.loading = true;

            try {
                // Prepare metadata payload
                const payload = {
                    title: this.editingBook.title,
                    authors: this.editingBook.authors,
                    publisher: this.editingBook.publisher,
                    comments: this.editingBook.comments,
                };

                // Include cover data if uploaded
                if (this.editingBook.coverData) {
                    payload.coverData = this.editingBook.coverData;
                }

                // Call metadata API
                const response = await fetch(`/api/metadata-and-cover/${this.editingBook.id}`, {
                    method: 'PUT',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify(payload),
                });

                const result = await response.json();

                if (!response.ok) {
                    // Handle error array from server
                    const errorMsg = result.errors
                        ? result.errors.join('\n')
                        : 'Failed to update metadata';
                    throw new Error(errorMsg);
                }

                console.log('✅ Metadata updated successfully');

                // Reload books to reflect changes
                await this.loadBooks();

                this.showEditMetadata = false;
                this.editingBook = null;

                // Show success message
                alert('Metadata updated successfully!');
            } catch (error) {
                console.error('Failed to save metadata:', error);
                alert(`Failed to save metadata: ${error.message}`);
            } finally {
                this.loading = false;
            }
        },

        /**
         * Handle cover art upload
         */
        handleCoverUpload(event) {
            const file = event.target.files[0];
            if (file) {
                const reader = new FileReader();
                reader.onload = (e) => {
                    this.editingBook.coverData = e.target.result;
                    console.log('📷 Cover art loaded');
                };
                reader.readAsDataURL(file);
            }
        },
    };
}
