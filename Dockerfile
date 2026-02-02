FROM python:3.11-slim

# Install system dependencies for lxml, Cairo, and SVG rendering
RUN apt-get update && apt-get install -y \
    build-essential \
    pkg-config \
    libxml2-dev \
    libxslt1-dev \
    libcairo2-dev \
    libpango1.0-dev \
    libglib2.0-dev \
    fontconfig \
    && rm -rf /var/lib/apt/lists/*

# Install COMPREHENSIVE font collection for maximum compatibility
# This ensures designs from any source (AI, Figma, etc.) render correctly
RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-liberation \
    fonts-liberation2 \
    fonts-dejavu \
    fonts-dejavu-core \
    fonts-dejavu-extra \
    fonts-freefont-ttf \
    fonts-noto-core \
    fonts-noto-ui-core \
    fonts-urw-base35 \
    fonts-font-awesome \
    && fc-cache -f -v \
    && rm -rf /var/lib/apt/lists/*

# Installed fonts provide equivalents for:
# - Liberation: Arial, Times New Roman, Courier (metrically compatible!)
# - DejaVu: Comprehensive weights (Regular, Bold, Italic, BoldItalic)
# - Noto: Google's comprehensive Unicode font
# - URW: PostScript base fonts
# - FreeFonts: GNU free fonts

# Set working directory
WORKDIR /app

# Copy requirements first (for layer caching)
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download rembg model (176MB) during build so it's cached in the image
# This prevents downloading it every time the container starts
RUN python3 -c "from rembg import remove, new_session; session = new_session('u2net'); print('✅ rembg model cached in Docker image')"

# Copy application code
COPY . .

# Create necessary directories
RUN mkdir -p temp output uploads databases

# Expose port (Railway will override this)
EXPOSE 8000

# Run the application with Gunicorn (production server)
# Uses $PORT from Railway environment variable
CMD gunicorn -w 2 -b 0.0.0.0:$PORT --timeout 600 --threads 2 --graceful-timeout 60 app:app
