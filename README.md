# YPB Label & Mockup Generator

An automated system for generating production-ready labels and photorealistic product mockups from designer-approved templates.

---

## Overview

This application takes a finalized Illustrator/SVG label template and generates labels for your entire product line by replacing only the data fields (product name, dosage, SKU, CAS number, molecular weight) — preserving all design, fonts, colors, and layout exactly as the designer intended.

**Key features:**
- Batch label generation: 90+ labels in ~35 seconds
- Output: SVG + JPG at 2400 DPI (4200×1800 px, print-ready)
- AI-powered mockup generation (Google Gemini) — photorealistic product photos
- Automatic placeholder detection — zero manual template editing required
- Web-based UI accessible from any browser

---

## Installation Options

There are two ways to run this application. **Docker is recommended** — it requires no manual dependency installation and works identically on any system.

| | Docker | Manual (Python) |
|---|---|---|
| Setup time | ~15 min (one-time build) | ~30 min |
| Dependencies | Docker Desktop only | Python, Cairo, pip |
| Works on | macOS, Windows, Linux | macOS, Linux |
| Recommended for | Everyone | Developers |

---

## Option A: Docker (Recommended)

### Step 1 — Install Docker Desktop

Download and install Docker Desktop from: **https://www.docker.com/products/docker-desktop**

After installation, launch Docker Desktop and wait until it shows **"Docker is running"** in the system tray.

> **Windows users**: During Docker installation, if asked about WSL 2 — click **Install** and follow the prompts. Restart your computer if required.

### Step 2 — Get a Gemini API Key

The application uses Google Gemini AI for mockup generation (free tier is sufficient).

1. Go to: **https://aistudio.google.com/apikey**
2. Sign in with a Google account
3. Click **Create API key**
4. Copy the key — you'll need it in Step 4

### Step 3 — Clone the repository

Open a terminal (macOS/Linux) or Command Prompt / PowerShell (Windows):

```bash
git clone https://github.com/lumizone/Ypb-publisch.git
cd Ypb-publisch
```

Or download as ZIP from GitHub and extract it.

### Step 4 — Create your environment file

Copy the example file:

```bash
# macOS / Linux
cp .env.example .env.local

# Windows (Command Prompt)
copy .env.example .env.local
```

Open `.env.local` in any text editor and fill in your values:

```
GEMINI_API_KEY=paste_your_key_here
AUTH_USER=Admin
AUTH_PASS=choose_a_password
DISABLE_AUTH=true
```

> Leave `DISABLE_AUTH=true` for local use. Set it to `false` if the app is accessible from the internet.

### Step 5 — Build the Docker image

This step downloads all fonts, AI models, and dependencies. It only needs to run **once** — subsequent starts are instant.

```bash
docker build -t ypb-generator .
```

**Expected build time**: 10–20 minutes depending on your internet speed.

During the build you'll see output like:
```
📥 Downloading Microsoft Core Fonts...
✅ Installed 11 Microsoft Core Fonts
📥 Downloading Google Fonts repository (1500+ fonts)...
✅ Installed 3247 Google Fonts
✅ rembg model cached in Docker image
```

If any font download shows `⚠ failed` — that's normal, fallback fonts are used automatically.

### Step 6 — Run the application

```bash
docker run -d \
  --name ypb \
  -p 8000:8000 \
  --env-file .env.local \
  -v "$(pwd)/output:/app/output" \
  -v "$(pwd)/uploads:/app/uploads" \
  -v "$(pwd)/databases:/app/databases" \
  ypb-generator
```

**Windows (Command Prompt)** — use `%cd%` instead of `$(pwd)`:
```
docker run -d --name ypb -p 8000:8000 --env-file .env.local -v "%cd%/output:/app/output" -v "%cd%/uploads:/app/uploads" -v "%cd%/databases:/app/databases" ypb-generator
```

**Windows (PowerShell)**:
```powershell
docker run -d --name ypb -p 8000:8000 --env-file .env.local -v "${PWD}/output:/app/output" -v "${PWD}/uploads:/app/uploads" -v "${PWD}/databases:/app/databases" ypb-generator
```

### Step 7 — Open the application

Open your browser at: **http://localhost:8000**

---

### Docker — everyday usage

```bash
# Stop the application
docker stop ypb

# Start again (no rebuild needed)
docker start ypb

# Restart
docker restart ypb

# View logs
docker logs ypb
docker logs -f ypb   # follow in real time

# Remove the container (keeps the image, so rebuild not needed)
docker rm -f ypb
```

### Docker — updating to a new version

```bash
# Pull latest code
git pull

# Remove old container
docker rm -f ypb

# Rebuild image (only needed if requirements.txt or Dockerfile changed)
docker build -t ypb-generator .

# Start again
docker run -d --name ypb -p 8000:8000 --env-file .env.local \
  -v "$(pwd)/output:/app/output" \
  -v "$(pwd)/uploads:/app/uploads" \
  -v "$(pwd)/databases:/app/databases" \
  ypb-generator
```

### Docker — troubleshooting

**"Cannot connect to the Docker daemon" / Docker not running**
→ Open Docker Desktop and wait until it shows "Docker is running"

**Port 8000 already in use**
→ Change `-p 8000:8000` to `-p 8080:8000` and open `http://localhost:8080`

**Container exits immediately**
→ Check logs: `docker logs ypb` — most likely the `.env.local` file is missing or has wrong values

**Generated files not appearing on disk**
→ Make sure you included the `-v` volume flags in the `docker run` command. Without them, files are generated inside the container only.

**"no space left on device" during build**
→ The image is ~4-5 GB. Open Docker Desktop → Settings → Resources → increase Disk image size to at least 20 GB

---

## Option B: Manual Installation (Python)

Use this method if you prefer not to use Docker or are running on a server without Docker.

### Prerequisites

- Python 3.9+
- Cairo library — see [INSTALL_CAIRO.md](INSTALL_CAIRO.md)
- Gemini API key — see [Step 2 above](#step-2--get-a-gemini-api-key)

### 1. Clone the repository

```bash
git clone https://github.com/lumizone/Ypb-publisch.git
cd Ypb-publisch
```

### 2. Install Cairo

**macOS:**
```bash
brew install cairo pkg-config
```

**Ubuntu/Debian:**
```bash
sudo apt-get install libcairo2-dev pkg-config python3-dev build-essential
```

For detailed instructions and troubleshooting: [INSTALL_CAIRO.md](INSTALL_CAIRO.md)

### 3. Create a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate   # macOS/Linux
# or: .venv\Scripts\activate  (Windows)
```

### 4. Install Python dependencies

```bash
pip install -r requirements.txt
```

This may take a few minutes (installs CairoSVG, rembg, Pillow, Flask, etc.).

### 5. Configure environment

```bash
cp .env.example .env.local
```

Edit `.env.local`:
```
GEMINI_API_KEY=paste_your_key_here
AUTH_USER=Admin
AUTH_PASS=choose_a_password
DISABLE_AUTH=true
```

### 6. Start the application

```bash
./start.sh
```

Then open: **http://localhost:8000**

**Alternative:**
```bash
source .venv/bin/activate
python app.py
```

**Other commands:**
```bash
./stop.sh      # stop the application
./restart.sh   # restart
tail -f /tmp/flask_app.log   # view logs
```

**macOS Apple Silicon (M1/M2/M3) — if Cairo is not found:**
```bash
export PKG_CONFIG_PATH="/opt/homebrew/lib/pkgconfig:$PKG_CONFIG_PATH"
export DYLD_LIBRARY_PATH="/opt/homebrew/lib:$DYLD_LIBRARY_PATH"
./start.sh
```

---

## Using the Application

### Three generators are available:

#### Label Generator (Standalone)
1. Upload your label template (SVG or Adobe Illustrator `.ai` file)
2. The system auto-detects all text fields (product name, dosage, SKU, CAS, MW)
3. Select your product database (CSV)
4. Click **Generate Labels**
5. Download the ZIP archive

**Output:**
```
Labels/
  YPB.211/
    YPB.211.svg
    YPB.211.jpg
  YPB.212/
    YPB.212.svg
    YPB.212.jpg
```

#### Mockup Generator (Standalone)
1. Upload a vial/product photo
2. Select or upload label files
3. Click **Generate Mockups**
4. Download the ZIP archive

**Output:**
```
Mockups/
  YPB.211.png
  YPB.212.png
```

#### Combined Generator (Recommended)
Generates labels and mockups in one workflow:

1. **Upload Vial** — your product photo
2. **Label Template** — SVG or AI file
3. **Template Preview** — verify text area detection
4. **Product Data** — select CSV database, choose products
5. **Generate Labels** — batch generate all labels
6. **Generate Mockups** — batch generate all mockups
7. **Download All** — combined ZIP with labels + mockups

**Output:**
```
Labels/
  YPB.211/
    YPB.211.svg
    YPB.211.jpg
Mockups/
  YPB.211.png
```

---

## Product Database

The system uses a CSV file with 5 columns:

```csv
SKU,Product,Dosage,CAS Number,Molecular Weight
YPB.211,Sermorelin,10mg,114466-38-5,3357.88 Da
YPB.212,BPC-157,5mg,137525-51-0,1419.55 Da
```

Column names are flexible — the system auto-detects them:

| Field | Accepted column names |
|-------|-----------------------|
| SKU | `SKU`, `sku` |
| Product name | `Product`, `product_name`, `Name` |
| Dosage | `Ingredients`, `Dosage`, `dosage`, `Composition` |
| CAS Number | `CAS`, `CAS Number`, `cas_number` |
| Molecular Weight | `MW`, `M.W.`, `Molecular Weight` |

The default database is `databases/YPB_data_Arkusz3.csv` (91 products).

### Importing a new database

In the **Database** tab of the web UI:
1. Click **Import CSV**
2. Upload your CSV file
3. Map columns to fields (auto-mapped if names match)
4. Click **Import**

---

## Template Preparation

The system supports:
- **SVG files** — exported from Illustrator (preferred)
- **Adobe Illustrator `.ai` files** — auto-converted to SVG on upload

**Auto-detection** (zero manual work): If your template contains actual values from the database (e.g., `"Sermorelin"`, `"114466-38-5"`, `"YPB.211"`), the system will automatically identify which text element corresponds to which field.

**Manual placeholders** (optional): You can add `data-placeholder` attributes to text elements in your SVG:
```xml
<text data-placeholder="product_name">Sermorelin</text>
<text data-placeholder="ingredients">10mg</text>
<text data-placeholder="sku">YPB.211</text>
<text data-placeholder="cas">114466-38-5</text>
<text data-placeholder="mw">3357.88 Da</text>
```

---

## Railway Deployment (Cloud)

The application includes a `Procfile` and `Dockerfile` for deployment on [Railway](https://railway.app).

1. Push to a GitHub repository
2. Create a new project on Railway, connect the repo
3. Add environment variables in Railway dashboard:
   - `GEMINI_API_KEY`
   - `AUTH_USER`
   - `AUTH_PASS`
4. Deploy — Railway auto-detects the Dockerfile and builds the image

Recommended Railway plan: **Pro** (8 CPU / 8 GB RAM) for long-running mockup generation jobs.

---

## Troubleshooting

**Mockup generation fails / Gemini API error**
→ Check that `GEMINI_API_KEY` is set correctly
→ Verify the key is active at https://aistudio.google.com/apikey

**Labels generate but text is wrong or garbled**
→ The template uses a custom-encoded font. The system falls back to AI-based text detection automatically. If issues persist, re-export the template from Illustrator as SVG with "Outline Text" disabled.

**CSV import fails**
→ Ensure the file is UTF-8 encoded
→ SKU, Product, and Dosage columns must be present (CAS and MW are optional)

**"no library called cairo-2 was found" (manual install)**
→ See [INSTALL_CAIRO.md](INSTALL_CAIRO.md)

---

## System Requirements

| | Docker | Manual |
|---|---|---|
| OS | macOS, Windows 10+, Linux | macOS, Linux |
| RAM | 4 GB+ | 2 GB+ |
| Disk | 10 GB free (image ~4-5 GB) | 2 GB free |
| CPU | Any modern CPU | Any modern CPU |

---

## File Structure

```
YPBv2/
├── app.py                    # Flask web application
├── app_dashboard.html        # Frontend UI
├── ai_converter.py           # AI/PDF → SVG conversion
├── text_replacer.py          # Text replacement engine
├── text_formatter.py         # Text wrapping & font sizing
├── template_parser.py        # SVG template parsing
├── batch_processor.py        # Parallel batch processing
├── renderer.py               # SVG → PNG/JPG rendering
├── csv_manager.py            # Database management
├── config.py                 # Configuration
├── Dockerfile                # Docker image definition
├── requirements.txt          # Python dependencies
├── .env.example              # Environment variables template
├── databases/
│   └── YPB_data_Arkusz3.csv  # Product database (91 products)
├── fonts/                    # Bundled fonts (required)
├── uploads/                  # Uploaded templates (auto-managed)
├── output/                   # Generated files (auto-managed)
└── temp/                     # Temporary files (auto-cleaned)
```

---

## License

Internal use only.
