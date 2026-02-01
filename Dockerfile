FROM python:3.11-slim

# Install system dependencies for lxml, Cairo, and SVG rendering
RUN apt-get update && apt-get install -y \
    libxml2 \
    libxslt1.1 \
    libcairo2 \
    libpango1.0-0 \
    libgdk-pixbuf-2.0-0 \
    librsvg2-2 \
    zlib1g \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first (for layer caching)
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create necessary directories
RUN mkdir -p temp output uploads databases

# Expose port (Railway will override this)
EXPOSE 8000

# Run the application
CMD ["python", "app.py"]
