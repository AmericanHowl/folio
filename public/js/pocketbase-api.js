/**
 * PocketBase API Client
 *
 * Documentation: https://pocketbase.io/docs/
 */

class FolioDatabase {
    constructor(baseUrl) {
        this.pb = new PocketBase(baseUrl || 'http://localhost:8090');
    }

    /**
     * Initialize the database connection
     */
    async init() {
        // Auto-refresh authentication if needed
        this.pb.authStore.onChange(() => {
            console.log('Auth state changed:', this.pb.authStore.isValid);
        });
    }

    /**
     * Get all book requests
     * @returns {Promise<Array>} Array of request objects
     */
    async getRequests() {
        try {
            const records = await this.pb.collection('requests').getFullList({
                sort: '-created',
            });
            return records;
        } catch (error) {
            console.error('Error fetching requests:', error);
            return [];
        }
    }

    /**
     * Create a new book request
     * @param {Object} requestData - Request data
     * @param {string} requestData.title - Book title
     * @param {string} requestData.author - Book author
     * @param {string} requestData.requester - Name of requester
     * @param {string} requestData.status - Status (requested, searching, ready)
     * @returns {Promise<Object>} Created request
     */
    async createRequest(requestData) {
        try {
            const record = await this.pb.collection('requests').create({
                ...requestData,
                status: requestData.status || 'requested',
            });
            return record;
        } catch (error) {
            console.error('Error creating request:', error);
            throw error;
        }
    }

    /**
     * Update a request status
     * @param {string} requestId - Request ID
     * @param {string} status - New status
     * @returns {Promise<Object>} Updated request
     */
    async updateRequestStatus(requestId, status) {
        try {
            const record = await this.pb.collection('requests').update(requestId, {
                status: status,
            });
            return record;
        } catch (error) {
            console.error('Error updating request:', error);
            throw error;
        }
    }

    /**
     * Delete a request
     * @param {string} requestId - Request ID
     * @returns {Promise<boolean>} Success status
     */
    async deleteRequest(requestId) {
        try {
            await this.pb.collection('requests').delete(requestId);
            return true;
        } catch (error) {
            console.error('Error deleting request:', error);
            return false;
        }
    }

    /**
     * Subscribe to real-time request updates
     * @param {Function} callback - Callback function for updates
     * @returns {Function} Unsubscribe function
     */
    subscribeToRequests(callback) {
        return this.pb.collection('requests').subscribe('*', callback);
    }

    /**
     * Get user preferences
     * @returns {Promise<Object>} User preferences
     */
    async getPreferences() {
        try {
            const records = await this.pb.collection('preferences').getFullList();
            return records[0] || {};
        } catch (error) {
            console.error('Error fetching preferences:', error);
            return {};
        }
    }

    /**
     * Save user preferences
     * @param {Object} preferences - Preferences object
     * @returns {Promise<Object>} Saved preferences
     */
    async savePreferences(preferences) {
        try {
            const existing = await this.getPreferences();

            if (existing.id) {
                return await this.pb.collection('preferences').update(existing.id, preferences);
            } else {
                return await this.pb.collection('preferences').create(preferences);
            }
        } catch (error) {
            console.error('Error saving preferences:', error);
            throw error;
        }
    }

    /**
     * Test connection to PocketBase
     * @returns {Promise<boolean>} True if connection successful
     */
    async testConnection() {
        try {
            await this.pb.health.check();
            return true;
        } catch (error) {
            console.error('PocketBase connection test failed:', error);
            return false;
        }
    }
}
