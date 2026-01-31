# Quick Start Guide

## Installation

1. **Install system dependencies:**

   **macOS:**
   ```bash
   brew install cairo pkg-config
   ```

   **Ubuntu/Debian:**
   ```bash
   sudo apt-get install libcairo2-dev pkg-config python3-dev
   ```

   **Windows:**
   - Download and install GTK+ runtime from: https://github.com/tschoonj/GTK-for-Windows-Runtime-Environment-Installer

2. **Install Python dependencies:**
   ```bash
   # On macOS, use setup script to configure environment
   source setup_env.sh
   python3 -m pip install -r requirements.txt
   
   # Or manually:
   # export PKG_CONFIG_PATH="/opt/homebrew/lib/pkgconfig:$PKG_CONFIG_PATH"
   # export DYLD_LIBRARY_PATH="/opt/homebrew/lib:$DYLD_LIBRARY_PATH"
   # python3 -m pip install -r requirements.txt
   ```

## Usage

### Command Line (Recommended)

**Basic usage:**
```bash
# Activate virtual environment first
source .venv/bin/activate

# Then run (or use the run.sh helper script)
python cli.py example_template.svg "YPB- database - Products.csv" -o output/

# Or use the helper script (automatically activates venv and sets paths)
./run.sh cli.py example_template.svg "YPB- database - Products.csv" -o output/
```

**With ZIP output:**
```bash
source .venv/bin/activate
python cli.py example_template.svg "YPB- database - Products.csv" -o output/ -z labels.zip
```

**Parallel processing (faster for large batches):**
```bash
source .venv/bin/activate
python cli.py example_template.svg "YPB- database - Products.csv" -o output/ -w 4
```

### Web Interface

1. **Start the server:**
   ```bash
   # Activate virtual environment first
   source .venv/bin/activate
   python app.py
   
   # Or use the helper script
   ./run.sh app.py
   ```

2. **Open your browser:**
   ```
   http://localhost:8000
   ```

3. **Upload files and generate:**
   - Select your template file (SVG/PDF)
   - Select your CSV file
   - Click "Generate Labels"
   - Download the ZIP file when complete

## Template Preparation

### From Adobe Illustrator:

1. **Create your label design** with three text fields:
   - Product Name
   - Ingredients
   - SKU

2. **Name the text layers** (important!):
   - Layer 1: `product_name`
   - Layer 2: `ingredients`
   - Layer 3: `sku`

3. **Export as SVG:**
   - File → Export → Export As...
   - Format: SVG (svg)
   - Click "Export"
   - In the SVG Options dialog:
     - Check "Use Artboards" if needed
     - Ensure "Preserve Illustrator Editing Capabilities" is checked
     - Ensure "Include SVG IDs" is checked

4. **Verify the exported SVG** has IDs on text elements:
   ```xml
   <text id="product_name">...</text>
   <text id="ingredients">...</text>
   <text id="sku">...</text>
   ```

### Alternative: Use Placeholders in Text

If Illustrator doesn't preserve layer names as IDs, you can use text placeholders:

1. Type the placeholder text directly in Illustrator:
   - `{product_name}`
   - `{ingredients}`
   - `{sku}`

2. Export as SVG

3. The system will find and replace these placeholders

## CSV Format

Your CSV file must have these columns (case-insensitive):
- `Product` or `product_name`
- `Ingredients` or `ingredients`
- `SKU` or `sku`

**Example:**
```csv
Product,Ingredients,SKU
Sermorelin,10mg,YPB.211
BPC-157,5mg,YPB.212
```

## Output

The system generates:

- **PNG files** at 300 DPI (print-ready)
- **PDF files** as vector graphics (print-ready)
- **ZIP archive** containing all files in `/labels/` folder

File naming: `{product_name}_{sku}.{ext}`

## Troubleshooting

**"Missing required placeholders" error:**
- Verify your SVG has elements with IDs: `product_name`, `ingredients`, `sku`
- Or use placeholder text: `{product_name}`, `{ingredients}`, `{sku}`

**"Cairo rendering failed" error:**
- Install system dependencies (see Installation section)
- On macOS: `brew install cairo`
- On Linux: `sudo apt-get install libcairo2-dev`

**"CSV parsing error":**
- Ensure CSV has correct columns (Product, Ingredients, SKU)
- Check for BOM encoding issues (UTF-8 is preferred)

**Text doesn't fit:**
- This is expected - the system doesn't resize text
- Adjust your template to accommodate longer product names/ingredients
- The designer is responsible for ensuring text fits

## Next Steps

- Review the full README.md for detailed documentation
- Check example_template.svg for a working example
- Test with a small CSV first (2-3 products)
