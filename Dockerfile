FROM python:3.11-slim

# Install Calibre
RUN apt-get update && \
    apt-get install -y wget xz-utils && \
    wget -nv -O- https://download.calibre-ebook.com/linux-installer.sh | sh /dev/stdin && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create instance directory
RUN mkdir -p instance

# Expose port
EXPOSE 9099

# Set environment variables
ENV FLASK_APP=app
ENV FLASK_ENV=production
ENV PYTHONUNBUFFERED=1

# Run the application
CMD ["python", "run.py"]
