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
    wget \
    cabextract \
    && rm -rf /var/lib/apt/lists/*

# Install Microsoft Core Fonts (Arial, Times New Roman, Courier, etc.)
# These are the ACTUAL fonts used in Adobe Illustrator and Microsoft Office
# NOTE: Build continues even if font download fails (Liberation fonts are fallback)
RUN set -x \
    && mkdir -p /tmp/msfonts \
    && cd /tmp/msfonts \
    && echo "📥 Downloading Microsoft Core Fonts from SourceForge..." \
    && (wget --timeout=30 --tries=3 https://downloads.sourceforge.net/project/corefonts/the%20fonts/final/andale32.exe || echo "⚠ andale32 failed") \
    && (wget --timeout=30 --tries=3 https://downloads.sourceforge.net/project/corefonts/the%20fonts/final/arial32.exe || echo "⚠ arial32 failed") \
    && (wget --timeout=30 --tries=3 https://downloads.sourceforge.net/project/corefonts/the%20fonts/final/arialb32.exe || echo "⚠ arialb32 failed") \
    && (wget --timeout=30 --tries=3 https://downloads.sourceforge.net/project/corefonts/the%20fonts/final/comic32.exe || echo "⚠ comic32 failed") \
    && (wget --timeout=30 --tries=3 https://downloads.sourceforge.net/project/corefonts/the%20fonts/final/courie32.exe || echo "⚠ courie32 failed") \
    && (wget --timeout=30 --tries=3 https://downloads.sourceforge.net/project/corefonts/the%20fonts/final/georgi32.exe || echo "⚠ georgi32 failed") \
    && (wget --timeout=30 --tries=3 https://downloads.sourceforge.net/project/corefonts/the%20fonts/final/impact32.exe || echo "⚠ impact32 failed") \
    && (wget --timeout=30 --tries=3 https://downloads.sourceforge.net/project/corefonts/the%20fonts/final/times32.exe || echo "⚠ times32 failed") \
    && (wget --timeout=30 --tries=3 https://downloads.sourceforge.net/project/corefonts/the%20fonts/final/trebuc32.exe || echo "⚠ trebuc32 failed") \
    && (wget --timeout=30 --tries=3 https://downloads.sourceforge.net/project/corefonts/the%20fonts/final/verdan32.exe || echo "⚠ verdan32 failed") \
    && (wget --timeout=30 --tries=3 https://downloads.sourceforge.net/project/corefonts/the%20fonts/final/webdin32.exe || echo "⚠ webdin32 failed") \
    && echo "📦 Extracting font files..." \
    && for exe in *.exe; do \
         if [ -f "$exe" ]; then \
           cabextract -q "$exe" 2>/dev/null || echo "⚠ Failed to extract $exe"; \
         fi \
       done \
    && mkdir -p /usr/share/fonts/truetype/msttcorefonts \
    && if ls *.ttf >/dev/null 2>&1; then \
         cp *.ttf /usr/share/fonts/truetype/msttcorefonts/ \
         && echo "✅ Installed $(ls *.ttf | wc -l) Microsoft Core Fonts"; \
       else \
         echo "⚠ No TTF files found - Liberation fonts will be used as fallback"; \
       fi \
    && fc-cache -f -v \
    && cd / \
    && rm -rf /tmp/msfonts \
    && echo "🔍 Font verification:" \
    && fc-list | grep -i "arial\|liberation" | head -10 || true

# Install Google Fonts - COMPREHENSIVE COLLECTION (1500+ font families)
# This gives us access to fonts like Montserrat (Gotham alternative), Inter (Acumin alternative),
# Roboto, Open Sans, and thousands of other high-quality fonts
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && echo "📥 Downloading Google Fonts repository (1500+ fonts)..." \
    && git clone --depth 1 https://github.com/google/fonts.git /tmp/gfonts \
    && echo "📦 Installing Google Fonts..." \
    && mkdir -p /usr/share/fonts/truetype/google-fonts \
    && find /tmp/gfonts -name "*.ttf" -exec cp {} /usr/share/fonts/truetype/google-fonts/ \; \
    && echo "✅ Installed $(find /usr/share/fonts/truetype/google-fonts -name "*.ttf" | wc -l) Google Fonts" \
    && fc-cache -f -v \
    && rm -rf /tmp/gfonts \
    && apt-get remove -y git \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/* \
    && echo "🔍 Google Fonts verification:" \
    && fc-list | grep -i "montserrat\|inter\|roboto" | head -5 || true

# Installed fonts:
# - Microsoft Core: Arial, Arial Bold, Arial Italic, Arial Bold Italic
#                   Times New Roman (all weights), Courier New (all weights)
#                   Verdana, Georgia, Trebuchet, Comic Sans, Impact, Webdings
# - Liberation: Metric-compatible fallbacks
# - DejaVu: Comprehensive weights (Regular, Bold, Italic, BoldItalic)
# - Noto: Google's comprehensive Unicode font
# - URW: PostScript base fonts
# - FreeFonts: GNU free fonts
# - Google Fonts: 1500+ families (Montserrat, Inter, Roboto, Open Sans, Lato, Poppins, etc.)

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
# 1 worker x 16 threads = shared in-memory state (progress_tracker, background_results)
# Multiple workers cause progress bar to break (each worker has separate memory)
CMD ["sh", "-c", "gunicorn -w 1 -b 0.0.0.0:${PORT:-8000} --timeout 900 --threads 16 --graceful-timeout 120 app:app"]
