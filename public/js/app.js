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
        showBrowser: false,
        showInitialSetup: false,
        isEditingMetadata: false,
        editingBook: null,

        // View mode
        viewMode: 'rows', // 'grid' or 'rows'

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
        hardcoverToken: false, // Boolean indicating if token is set

        // Directory Browser
        browserPath: '',
        browserParent: null,
        browserEntries: [],

        // Hardcover integration
        hardcoverSearchQuery: '',
        hardcoverBooks: [],
        hardcoverSections: [],
        hardcoverLoading: false,
        selectedHardcoverBook: null,

        // Requests
        requestedBooks: [],

        // Genre filtering
        selectedGenre: null,

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

            // Load requested books
            await this.loadRequestedBooks();

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
                // Just check the current book count
                const currentCount = this.books.length;

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
                this.hardcoverToken = data.hardcover_token || false;
                console.log('📖 Loaded config:', data);
            } catch (error) {
                console.error('Failed to load config:', error);
            }
        },

        /**
         * Save settings (library path and Hardcover token to server)
         */
        async saveSettings() {
            try {
                // Build payload with all settings
                const payload = {
                    calibre_library: this.calibreLibraryPath
                };

                // Only send token if it's a non-empty string (not a boolean)
                if (typeof this.hardcoverToken === 'string' && this.hardcoverToken.trim()) {
                    payload.hardcover_token = this.hardcoverToken.trim();
                }

                const response = await fetch('/api/config', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify(payload),
                });

                const result = await response.json();
                if (result.success) {
                    console.log('✅ Settings saved');
                    // Update local state with returned config
                    this.hardcoverToken = result.config.hardcover_token;
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
         * Enter edit mode for metadata
         */
        openEditMetadata(book) {
            // Copy book data and convert arrays to comma-separated strings for editing
            this.editingBook = {
                ...book,
                authors: Array.isArray(book.authors) ? book.authors.join(', ') : (book.authors || ''),
                tags: Array.isArray(book.tags) ? book.tags.join(', ') : (book.tags || ''),
                pubdate: book.pubdate ? new Date(book.pubdate).getFullYear().toString() : ''
            };
            this.isEditingMetadata = true;
            // Keep selectedBook open - the same modal transforms to edit mode
        },

        /**
         * Cancel editing and return to view mode
         */
        cancelEditMetadata() {
            this.isEditingMetadata = false;
            this.editingBook = null;
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

                // Update the selectedBook with new data
                const updatedBook = this.books.find(b => b.id === this.editingBook.id);
                if (updatedBook) {
                    this.selectedBook = updatedBook;
                }

                // Return to view mode
                this.isEditingMetadata = false;
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

        /**
         * Handle cover art drag & drop
         */
        handleCoverDrop(event) {
            const file = event.dataTransfer.files[0];
            if (file && file.type.startsWith('image/')) {
                const reader = new FileReader();
                reader.onload = (e) => {
                    this.editingBook.coverData = e.target.result;
                    console.log('📷 Cover art dropped');
                };
                reader.readAsDataURL(file);
            } else {
                alert('Please drop an image file');
            }
        },

        /**
         * Search for metadata (placeholder - not implemented yet)
         */
        searchMetadata() {
            console.log('🔍 Search metadata clicked (not yet implemented)');
            alert('Metadata search will be implemented in a future version. This will allow you to automatically fetch book information from online sources like Hardcover, Google Books, or Open Library.');
        },

        /**
         * Get unique authors from all books for autocomplete
         */
        getAuthors() {
            const authorsSet = new Set();
            this.books.forEach(book => {
                if (Array.isArray(book.authors)) {
                    book.authors.forEach(author => authorsSet.add(author));
                } else if (book.authors) {
                    authorsSet.add(book.authors);
                }
            });
            return Array.from(authorsSet).sort();
        },

        /**
         * Get unique publishers from all books for autocomplete
         */
        getPublishers() {
            const publishersSet = new Set();
            this.books.forEach(book => {
                if (book.publisher) {
                    publishersSet.add(book.publisher);
                }
            });
            return Array.from(publishersSet).sort();
        },

        /**
         * Get unique genres/tags from all books for autocomplete
         */
        getGenres() {
            const genresSet = new Set();
            this.books.forEach(book => {
                if (Array.isArray(book.tags)) {
                    book.tags.forEach(tag => genresSet.add(tag));
                }
            });
            return Array.from(genresSet).sort();
        },

        // ============================================
        // Hardcover Integration
        // ============================================

        /**
         * Search Hardcover for books
         */
        async searchHardcover() {
            if (!this.hardcoverSearchQuery.trim()) {
                return;
            }

            this.hardcoverLoading = true;
            this.hardcoverBooks = [];

            try {
                const response = await fetch(`/api/hardcover/search?q=${encodeURIComponent(this.hardcoverSearchQuery)}&limit=30`);
                const data = await response.json();

                if (data.error) {
                    console.error('Hardcover search error:', data.error);
                    alert('Hardcover search failed: ' + data.error);
                    return;
                }

                // Add library matching to results
                this.hardcoverBooks = this.matchWithLibrary(data.books || []);
                console.log(`🔍 Found ${this.hardcoverBooks.length} books on Hardcover`);
            } catch (error) {
                console.error('Failed to search Hardcover:', error);
                alert('Failed to search Hardcover: ' + error.message);
            } finally {
                this.hardcoverLoading = false;
            }
        },

        /**
         * Load trending books from Hardcover
         */
        async loadTrendingBooks() {
            if (!this.hardcoverToken) return;

            this.hardcoverLoading = true;

            try {
                const response = await fetch('/api/hardcover/trending?limit=20');
                const data = await response.json();

                if (data.error) {
                    console.error('Failed to load trending:', data.error);
                    return;
                }

                this.hardcoverBooks = this.matchWithLibrary(data.books || []);
                console.log(`📈 Loaded ${this.hardcoverBooks.length} trending books`);
            } catch (error) {
                console.error('Failed to load trending books:', error);
            } finally {
                this.hardcoverLoading = false;
            }
        },

        /**
         * Match Hardcover books with local library using fuzzy matching
         */
        matchWithLibrary(hardcoverBooks) {
            return hardcoverBooks.map(book => {
                // Check if already requested
                const isRequested = this.requestedBooks.some(r => r.id === book.id);

                // Fuzzy match with library
                const libraryMatch = this.findLibraryMatch(book);

                return {
                    ...book,
                    inLibrary: !!libraryMatch,
                    libraryBookId: libraryMatch?.id,
                    requested: isRequested
                };
            });
        },

        /**
         * Find a matching book in the local library using fuzzy logic
         */
        findLibraryMatch(hardcoverBook) {
            const hcTitle = this.normalizeForMatching(hardcoverBook.title);
            const hcAuthor = this.normalizeForMatching(hardcoverBook.author);

            for (const book of this.books) {
                const libTitle = this.normalizeForMatching(book.title);
                const libAuthor = this.normalizeForMatching(
                    Array.isArray(book.authors) ? book.authors.join(' ') : book.authors
                );

                // Check for title match
                const titleSimilarity = this.calculateSimilarity(hcTitle, libTitle);

                // Check for author match
                const authorSimilarity = this.calculateSimilarity(hcAuthor, libAuthor);

                // Consider it a match if title is very similar and author has some similarity
                if (titleSimilarity > 0.85 && authorSimilarity > 0.5) {
                    return book;
                }

                // Also match if both title and author are reasonably similar
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
                .replace(/[^a-z0-9\s]/g, '') // Remove punctuation
                .replace(/\s+/g, ' ')         // Normalize whitespace
                .trim();
        },

        /**
         * Calculate similarity between two strings (0-1)
         * Uses a simple approach based on common words
         */
        calculateSimilarity(str1, str2) {
            if (!str1 || !str2) return 0;
            if (str1 === str2) return 1;

            const words1 = new Set(str1.split(' ').filter(w => w.length > 2));
            const words2 = new Set(str2.split(' ').filter(w => w.length > 2));

            if (words1.size === 0 || words2.size === 0) {
                // Fallback to substring matching for short strings
                if (str1.includes(str2) || str2.includes(str1)) return 0.8;
                return 0;
            }

            const intersection = [...words1].filter(w => words2.has(w));
            const union = new Set([...words1, ...words2]);

            return intersection.length / union.size;
        },

        /**
         * Open modal for Hardcover book
         */
        openHardcoverModal(book) {
            this.selectedHardcoverBook = book;
        },

        /**
         * View a book in the library
         */
        viewInLibrary(hardcoverBook) {
            if (hardcoverBook.libraryBookId) {
                const book = this.books.find(b => b.id === hardcoverBook.libraryBookId);
                if (book) {
                    this.selectedHardcoverBook = null;
                    this.currentTab = 'library';
                    this.openBookModal(book);
                }
            }
        },

        // ============================================
        // Request Management
        // ============================================

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
         * Request a book from Hardcover
         */
        async requestBook(book) {
            try {
                const response = await fetch('/api/requests', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({ book }),
                });

                const data = await response.json();
                if (data.success) {
                    this.requestedBooks = data.books;
                    book.requested = true;
                    console.log(`📬 Requested: ${book.title}`);
                } else {
                    alert('Failed to request book: ' + (data.error || 'Unknown error'));
                }
            } catch (error) {
                console.error('Failed to request book:', error);
                alert('Failed to request book: ' + error.message);
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
        // Section View Helpers
        // ============================================

        /**
         * Get recently added books (sorted by timestamp)
         */
        getRecentBooks() {
            return [...this.books]
                .sort((a, b) => {
                    const dateA = a.timestamp ? new Date(a.timestamp) : new Date(0);
                    const dateB = b.timestamp ? new Date(b.timestamp) : new Date(0);
                    return dateB - dateA;
                })
                .slice(0, 15);
        },

        /**
         * Get top genres from the library
         */
        getTopGenres() {
            const genreCounts = {};
            this.books.forEach(book => {
                if (Array.isArray(book.tags)) {
                    book.tags.forEach(tag => {
                        genreCounts[tag] = (genreCounts[tag] || 0) + 1;
                    });
                }
            });

            return Object.entries(genreCounts)
                .sort((a, b) => b[1] - a[1])
                .slice(0, 6)
                .map(([genre]) => genre);
        },

        /**
         * Get top authors (those with most books)
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
                .filter(([_, count]) => count >= 2) // Only authors with 2+ books
                .sort((a, b) => b[1] - a[1])
                .slice(0, 3)
                .map(([author]) => author);
        },

        /**
         * Get books by a specific author
         */
        getBooksByAuthor(authorName) {
            return this.books.filter(book => {
                const author = Array.isArray(book.authors) ? book.authors[0] : book.authors;
                return author === authorName;
            }).slice(0, 10);
        },

        /**
         * Filter books by genre
         */
        filterByGenre(genre) {
            if (this.selectedGenre === genre) {
                // Deselect
                this.selectedGenre = null;
                this.filteredBooks = this.books;
            } else {
                this.selectedGenre = genre;
                this.filteredBooks = this.books.filter(book =>
                    Array.isArray(book.tags) && book.tags.includes(genre)
                );
            }
            this.updateDisplayedBooks();
            this.viewMode = 'grid'; // Switch to grid to show filtered results
        },
    };
}
