# Label Replication System

Automated label generation and mockup system that takes a designer-approved Adobe Illustrator template and generates production-ready labels for multiple products by replacing only three text fields: product name, ingredients, and SKU.

**Ostatnia aktualizacja:** 29 stycznia 2026 - Modernizacja Gemini API (google-genai SDK)

## Features

### Label Generation
- **Template-based generation**: Uses finalized Illustrator templates (SVG/PDF)
- **Deterministic text replacement**: Only replaces specified fields, preserves all styling
- **Batch processing**: Generate labels for 60-100+ products in minutes
- **Print-ready output**: PNG (300 DPI) and PDF (vector) formats
- **Organized delivery**: All files packaged in structured ZIP archives
- **No design changes**: Layout, fonts, colors, and positioning are locked

### Mockup Generation (AI-powered)
- **Gemini API integration**: Uses Google Gemini 2.5 Flash for realistic mockup generation
- **Auto-retry logic**: 3 attempts with AI verification
- **AI verification**: Validates SKU, product name, and dosage on mockups
- **Parallel processing**: Generate multiple mockups simultaneously (ThreadPoolExecutor)
- **Green screen removal**: Automatic background removal for transparent mockups
- **Production-ready**: High-quality, photorealistic product mockups

## Requirements

- Python 3.8+
- Required system libraries (for Cairo):
  - macOS: `brew install cairo pkg-config`
  - Ubuntu/Debian: `sudo apt-get install libcairo2-dev pkg-config`
  - Windows: Install GTK+ runtime
- **Gemini API Key** (for mockup generation):
  - Get from: https://ai.google.dev/
  - Set in `.env.local`: `GEMINI_API_KEY=your_key_here`

## Installation

1. Clone or download this repository

2. Install system dependencies (macOS):
```bash
brew install cairo pkg-config
```

3. Install Python dependencies:
```bash
python3 -m pip install -r requirements.txt
```

   **Note:** On macOS with Homebrew, you may need to set library paths. Use the setup script:
   ```bash
   source setup_env.sh
   python3 -m pip install -r requirements.txt
   ```

4. Verify installation:
```bash
# Activate virtual environment first
source .venv/bin/activate
python cli.py --help

# Or use the helper script
./run.sh cli.py --help
```

## Usage

### Command Line Interface

**Important:** Always activate the virtual environment first, or use the helper script:
```bash
# Activate virtual environment
source .venv/bin/activate

# Then run
python cli.py <template.svg> <products.csv> -o output/ -z labels.zip

# Or use the helper script (automatically activates venv and sets paths)
./run.sh cli.py <template.svg> <products.csv> -o output/ -z labels.zip
```

**Arguments:**
- `template`: Path to label template (SVG or PDF)
- `csv`: Path to product CSV file
- `-o, --output`: Output directory (default: `./output`)
- `-z, --zip`: ZIP file output path (optional)
- `-w, --workers`: Number of parallel workers (default: 1)

**Example:**
```bash
python cli.py template.svg "YPB- database - Products.csv" -o labels/ -z labels_batch.zip
```

### Web Interface

Start the Flask web server:

```bash
# Activate virtual environment first
source .venv/bin/activate
python app.py

# Or use the helper script
./run.sh app.py
```

Then open your browser to `http://localhost:8000` and use the admin UI to:
1. Upload your label template
2. Upload your product CSV
3. Generate labels
4. Download the ZIP archive

### CSV Format

Your CSV file should have these columns:
- `Product` (or `product_name`)
- `Ingredients` (or `ingredients`, `composition`)
- `SKU` (or `sku`)

**Example:**
```csv
Product,Ingredients,SKU
Sermorelin,10mg,YPB.211
BPC-157,5mg,YPB.212
```

## Template Preparation

### Illustrator Template Requirements

1. **Export format**: Export your Illustrator file as SVG (preferred) or PDF
2. **Placeholder identification**: The three text fields must be identifiable by one of:
   - Layer/object ID matching: `product_name`, `ingredients`, `sku`
   - Data attribute: `data-placeholder="product_name"`
   - Text content placeholder: `{product_name}` or `[product_name]`

3. **Field names** (must match exactly):
   - `product_name`
   - `ingredients`
   - `sku`

### SVG Template Example

```svg
<text id="product_name" x="100" y="50" style="font-family: Arial; font-size: 24px;">
  {product_name}
</text>
<text id="ingredients" x="100" y="100" style="font-family: Arial; font-size: 12px;">
  {ingredients}
</text>
<text id="sku" x="100" y="150" style="font-family: Arial; font-size: 10px;">
  {sku}
</text>
```

## Output Structure

Generated files are organized as:

```
/labels/
  product-name_sku.pdf
  product-name_sku.png
  ...
```

All files are packaged in a ZIP archive for easy delivery.

## Architecture

### Core Modules
- **template_parser.py**: Parses SVG/PDF templates and detects placeholders
- **data_mapper.py**: Loads and validates product data from CSV
- **text_replacer.py**: Replaces text while preserving all styling
- **text_formatter.py**: Intelligent text wrapping and font sizing
- **renderer.py**: Exports to PNG (300 DPI) and PDF (vector)
- **batch_processor.py**: Orchestrates batch generation
- **packager.py**: Creates organized ZIP archives
- **ai_converter.py**: AI/PDF to SVG conversion

### Web Application
- **app.py**: Flask web interface with REST API
  - Label generation endpoints
  - Mockup generation endpoints (Gemini API)
  - Database management endpoints
  - Progress tracking and file delivery

### Mockup Generation (AI)
- **Gemini SDK**: `google-genai>=1.47.0` (zaktualizowany 29.01.2026)
- **Functions**:
  - `_generate_mockup_for_product_with_retry()`: Generates mockups with retry logic
  - `_verify_mockup_with_vision()`: AI verification of mockup text
  - `add_green_background()`: Adds green screen background
  - `remove_background_with_reference()`: Green screen removal

## Constraints

- **No layout changes**: Elements cannot be moved or resized
- **No font substitution**: Fonts must be embedded or available server-side
- **Text overflow**: Designer is responsible for ensuring text fits bounds
- **AI files**: Must be exported to SVG/PDF before use (Phase 1)

## Error Handling

The system will:
- Validate templates before processing
- Skip individual products that fail (log error, continue batch)
- Provide detailed error messages
- Generate partial batches if some products fail

## Troubleshooting

**"Missing required placeholders" error:**
- Ensure your template has text elements with IDs: `product_name`, `ingredients`, `sku`
- Check that SVG exports preserve layer names/IDs

**"Rendering failed" error:**
- Verify Cairo libraries are installed correctly
- Check SVG file is valid XML
- Ensure fonts are embedded or available

**"CSV parsing error":**
- Verify CSV has correct column names (Product, Ingredients, SKU)
- Check for encoding issues (should be UTF-8)

## License

Internal use only.

## Support

For issues or questions, refer to the developer handoff documentation.
