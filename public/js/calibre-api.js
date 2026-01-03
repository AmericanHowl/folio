/**
 * Calibre Content Server API Client
 *
 * Documentation: https://manual.calibre-ebook.com/server.html
 */

class CalibreAPI {
    constructor(baseUrl) {
        this.baseUrl = baseUrl || 'http://localhost:8080';
    }

    /**
     * Get all books from the library
     * @param {Object} options - Query options
     * @param {number} options.limit - Maximum number of books to return
     * @param {number} options.offset - Number of books to skip
     * @param {string} options.query - Search query
     * @returns {Promise<Array>} Array of book objects
     */
    async getBooks(options = {}) {
        const { limit = 50, offset = 0, query = '' } = options;

        try {
            const params = new URLSearchParams({
                num: limit,
                offset: offset,
            });

            if (query) {
                params.append('query', query);
            }

            const response = await fetch(`${this.baseUrl}/ajax/search?${params}`);

            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }

            const data = await response.json();

            // Convert Calibre's format to our format
            return data.book_ids.map(id => ({
                id: id,
                ...data.metadata[id]
            }));
        } catch (error) {
            console.error('Error fetching books:', error);
            throw error;
        }
    }

    /**
     * Get detailed metadata for a specific book
     * @param {number} bookId - Book ID
     * @returns {Promise<Object>} Book metadata
     */
    async getBookMetadata(bookId) {
        try {
            const response = await fetch(`${this.baseUrl}/ajax/book/${bookId}`);

            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }

            return await response.json();
        } catch (error) {
            console.error(`Error fetching book ${bookId}:`, error);
            throw error;
        }
    }

    /**
     * Get the cover image URL for a book
     * @param {number} bookId - Book ID
     * @returns {string} Cover image URL
     */
    getCoverUrl(bookId) {
        return `${this.baseUrl}/get/cover/${bookId}`;
    }

    /**
     * Get the download URL for a book in a specific format
     * @param {number} bookId - Book ID
     * @param {string} format - Format (e.g., 'EPUB', 'PDF', 'MOBI')
     * @returns {string} Download URL
     */
    getDownloadUrl(bookId, format = 'EPUB') {
        return `${this.baseUrl}/get/${format}/${bookId}`;
    }

    /**
     * Search for books
     * @param {string} query - Search query
     * @returns {Promise<Array>} Array of matching books
     */
    async searchBooks(query) {
        return this.getBooks({ query });
    }

    /**
     * Get library metadata (total books, etc.)
     * @returns {Promise<Object>} Library stats
     */
    async getLibraryMetadata() {
        try {
            const response = await fetch(`${this.baseUrl}/ajax/library-info`);

            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }

            return await response.json();
        } catch (error) {
            console.error('Error fetching library metadata:', error);
            throw error;
        }
    }

    /**
     * Test connection to Calibre Content Server
     * @returns {Promise<boolean>} True if connection successful
     */
    async testConnection() {
        try {
            const response = await fetch(`${this.baseUrl}/ajax/library-info`);
            return response.ok;
        } catch (error) {
            console.error('Connection test failed:', error);
            return false;
        }
    }
}
