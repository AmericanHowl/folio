FROM python:3.11-slim

# Install calibre (includes calibredb)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    calibre \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy application files
COPY serve.py .
COPY public/ ./public/

# Create directory for config.json (will be mounted as volume)
RUN mkdir -p /app && touch /app/config.json

# Expose port
EXPOSE 9099

# Run the server
CMD ["python3", "serve.py"]
