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

## Prerequisites

- **Python 3.9+**
- **Cairo** (required for SVG rendering) — see [INSTALL_CAIRO.md](INSTALL_CAIRO.md)
- **Google Gemini API key** (required for mockup generation only)
  - Get one free at: https://aistudio.google.com/apikey

---

## Quick Start

### 1. Clone the repository

```bash
git clone <repository-url>
cd YPBv2
```

### 2. Create a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate   # macOS/Linux
# or: .venv\Scripts\activate  (Windows)
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment

```bash
cp .env.example .env.local
```

Edit `.env.local` and fill in your values:

```
GEMINI_API_KEY=your_gemini_api_key_here
AUTH_USER=Admin
AUTH_PASS=your_password_here
DISABLE_AUTH=true
```

### 5. Start the application

```bash
./start.sh
```

Then open your browser at **http://localhost:8000**

---

## Obtaining a Gemini API Key

1. Go to https://aistudio.google.com/apikey
2. Sign in with a Google account
3. Click **Create API key**
4. Copy the key into your `.env.local` file as `GEMINI_API_KEY=...`

The free tier is sufficient for generating mockups. Mockup generation uses the `gemini-2.5-flash-image` model.

---

## Usage

The application has three generators accessible from the web UI:

### Label Generator (Standalone)

1. Upload your label template (SVG or Adobe Illustrator `.ai` file)
2. The system auto-detects all text fields (product name, dosage, SKU, CAS, MW)
3. Select your product database (CSV)
4. Click **Generate Labels**
5. Download the ZIP archive

**Output ZIP structure:**
```
Labels/
  YPB.211/
    YPB.211.svg
    YPB.211.jpg
  YPB.212/
    YPB.212.svg
    YPB.212.jpg
```

### Mockup Generator (Standalone)

1. Upload a vial/product photo
2. Select or upload label files
3. Click **Generate Mockups**
4. Download the ZIP archive

**Output ZIP structure:**
```
Mockups/
  YPB.211.png
  YPB.212.png
```

### Combined Generator (Recommended)

Generates labels and mockups in one workflow:

1. **Upload Vial** — your product photo
2. **Label Template** — SVG or AI file
3. **Template Preview** — verify text area detection
4. **Product Data** — select CSV database, choose products
5. **Generate Labels** — batch generate all labels
6. **Generate Mockups** — batch generate all mockups
7. **Download All** — combined ZIP with labels + mockups

**Combined ZIP structure:**
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

**Column mapping** (auto-detected, column names are flexible):
| Field | Accepted names |
|-------|----------------|
| SKU | `SKU`, `sku` |
| Product name | `Product`, `product_name`, `Name` |
| Dosage | `Ingredients`, `Dosage`, `dosage`, `Composition` |
| CAS Number | `CAS`, `CAS Number`, `cas_number` |
| Molecular Weight | `MW`, `M.W.`, `Molecular Weight` |

The default database is located at `databases/YPB_data_Arkusz3.csv` (91 products).

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

**Auto-detection** (zero manual work required): If your template contains the actual values from the database (e.g., the text `"Sermorelin"`, `"114466-38-5"`, `"YPB.211"`), the system will automatically identify which text element is which field.

**Manual placeholders** (optional): You can add `data-placeholder` attributes to text elements in your SVG:
```xml
<text data-placeholder="product_name">Sermorelin</text>
<text data-placeholder="ingredients">10mg</text>
<text data-placeholder="sku">YPB.211</text>
<text data-placeholder="cas">114466-38-5</text>
<text data-placeholder="mw">3357.88 Da</text>
```

---

## Running (Alternative Methods)

```bash
# Start
./start.sh

# Stop
./stop.sh

# Restart
./restart.sh

# Check logs
tail -f /tmp/flask_app.log
```

Or run directly:
```bash
source .venv/bin/activate
python app.py
```

---

## Railway Deployment

The application includes a `Procfile` and `Dockerfile` for deployment on [Railway](https://railway.app).

1. Push to a GitHub repository
2. Create a new project on Railway, connect the repo
3. Add environment variables in Railway dashboard:
   - `GEMINI_API_KEY`
   - `AUTH_USER`
   - `AUTH_PASS`
4. Deploy

The app is configured for Railway's 8 CPU / 8 GB RAM instances. Recommended plan: Pro (for long-running mockup generation jobs).

---

## System Requirements

| Requirement | Minimum | Recommended |
|-------------|---------|-------------|
| Python | 3.9 | 3.11+ |
| RAM | 2 GB | 4 GB+ |
| CPU | 2 cores | 4+ cores |
| Disk | 500 MB | 2 GB+ |
| OS | macOS / Linux | macOS / Ubuntu |

---

## Troubleshooting

**"no library called cairo-2 was found"**
→ Install Cairo: see [INSTALL_CAIRO.md](INSTALL_CAIRO.md)

**Mockup generation fails / Gemini API error**
→ Check that `GEMINI_API_KEY` is set correctly in `.env.local`
→ Verify the key is active at https://aistudio.google.com/apikey

**Labels generate but text is wrong / garbled**
→ The template uses a custom-encoded font. The system will fall back to AI-based text detection automatically. If issues persist, try exporting the template as SVG from Illustrator with "Outline Text" disabled.

**CSV import fails**
→ Ensure the file is UTF-8 encoded
→ Check that SKU, Product, and Dosage columns are present (CAS and MW are optional)

**Application won't start on macOS (Apple Silicon)**
→ Run the following before starting:
```bash
export PKG_CONFIG_PATH="/opt/homebrew/lib/pkgconfig:$PKG_CONFIG_PATH"
export DYLD_LIBRARY_PATH="/opt/homebrew/lib:$DYLD_LIBRARY_PATH"
./start.sh
```

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
├── requirements.txt          # Python dependencies
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
