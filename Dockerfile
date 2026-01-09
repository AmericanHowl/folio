FROM python:3.11-slim

# Labels for container metadata (helps Portainer display info)
LABEL org.opencontainers.image.title="Folio"
LABEL org.opencontainers.image.description="Calibre library manager with Hardcover integration"
LABEL org.opencontainers.image.source="https://github.com/MykieRowan/folio"

# Install calibre (includes calibredb) and curl for health checks
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    calibre \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy application files
COPY serve.py .
COPY public/ ./public/

# Create empty config.json with valid JSON (avoids parse errors on first run)
RUN mkdir -p /app && echo '{}' > /app/config.json

# Set default environment variables for container
ENV CALIBREDB_PATH=/usr/bin/calibredb
ENV CALIBRE_LIBRARY=/data/calibre-library

# Expose port
EXPOSE 9099

# Health check for Portainer and orchestration tools
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:9099/api/config || exit 1

# Run the server
CMD ["python3", "serve.py"]
