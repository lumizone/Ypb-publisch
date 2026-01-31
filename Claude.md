# YPBv2 - Label & Mockup Generator

**Status**: ✅ Production Ready (31 stycznia 2026)
**Lokalizacja**: `/Users/lukasz/YPBv2`
**Port**: http://localhost:8000

---

## 🎯 AKTUALNY STAN APLIKACJI

### ✅ Zaimplementowano Async Mockup Generation (31.01.2026)

**Cel**: Możliwość przełączania kart w przeglądarce podczas generacji mockupów (15-20 minut)

**Implementacja**:
- ✅ Flask `threaded=True` - wielowątkowy serwer
- ✅ `@run_in_background` - background tasks
- ✅ JavaScript polling (500ms) - progress tracking
- ✅ Endpoint zwraca `job_id` natychmiast (~50ms)
- ✅ Parallel processing - 4 workers (ThreadPoolExecutor)
- ✅ Verification zachowana - side-by-side (bez zmian)

**Pliki zmodyfikowane**:
1. `app.py` - linie: 4708, 3143, 3326-3357, 3412-3424
2. `app_dashboard.html` - linie: 7690-7752, funkcja `fetchMockupGenerationResults()`

**Weryfikacja**: `./restart.sh` → http://localhost:8000

---

## 📋 GŁÓWNE FUNKCJE

### 1. **Label Generator**
- Upload template (SVG/AI)
- Upload CSV database (92 produkty)
- Batch generation: SVG + PNG (300 DPI) + PDF + JPG
- Intelligent text wrapping & formatting
- Auto-detection placeholders (`data-placeholder`)

### 2. **Mockup Generator**
- Upload vial image
- Gemini Vision API (gemini-2.5-flash-image)
- Green background removal
- Side-by-side verification (96% accuracy)
- Retry logic (3 attempts per mockup)
- Parallel processing (4 workers)

### 3. **Combined Generator**
- Step 1: Generate labels → ZIP
- Step 2: Generate mockups → ZIP
- Download All: Combined ZIP (labels + mockups by SKU)

### 4. **Archive Management**
- List all jobs (labels + mockups)
- Download archives
- Delete old files
- Storage statistics

---

## 🛠️ TECHNOLOGIE

**Backend**:
- Python 3.9 + Flask 3.0
- PyMuPDF (AI → SVG conversion @ 675 DPI)
- CairoSVG (SVG → PNG @ 300 DPI)
- ReportLab (SVG → PDF wektorowy)
- Pillow + rembg (background removal)

**API**:
- Google Gemini 2.5 Flash Image API
- `google-genai>=1.47.0` (nowy SDK 2026)

**Frontend**:
- HTML/JavaScript (single page app)
- Real-time progress tracking
- Drag & drop file upload

---

## 📁 STRUKTURA PROJEKTU

```
/Users/lukasz/YPBv2/
├── app.py (4709 linii)           # Flask application
├── app_dashboard.html            # Frontend UI
├── ai_converter.py               # AI → SVG (PyMuPDF)
├── text_replacer.py              # Text replacement engine
├── text_formatter.py             # Intelligent text wrapping
├── batch_processor.py            # Batch processing (parallel)
├── renderer.py                   # SVG → PNG/PDF/JPG
├── verification_side_by_side.py  # Gemini Vision verification
├── template_parser.py            # SVG template parsing
├── csv_manager.py                # CSV database handling
├── progress_tracker.py           # Thread-safe progress tracking
├── cleanup_utils.py              # Temp file cleanup
├── config.py                     # Configuration
├── .env.local                    # API keys
├── requirements.txt              # Python dependencies
├── databases/
│   └── YPB_final_databse.csv    # 92 produkty
├── temp/                         # Tymczasowe pliki (auto-cleanup)
├── output/                       # Wygenerowane labels & mockups
└── uploads/                      # Przesłane templates & images
```

---

## ⚙️ KONFIGURACJA

### Environment Variables (.env.local)
```bash
GEMINI_API_KEY=AIzaSyCSyrlmwF9LJ8haOrsC5bn4St-viT4wsMM
AUTH_USER=Admin
AUTH_PASS=admin123
DISABLE_AUTH=true
```

### Kluczowe Ustawienia (config.py)
```python
PNG_DPI = 300
PDF_VECTOR_MODE = True
MAX_CONCURRENT_JOBS = 4
GEMINI_MOCKUP_MODEL = 'gemini-2.5-flash-image'
AUTO_CLEANUP_HOURS = 24
```

---

## 🚀 URUCHOMIENIE

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

**URL**: http://localhost:8000

---

## 📊 WORKFLOW

### Combined Generator (Pełny przepływ):

1. **Upload Template** (SVG/AI)
   - AI files są konwertowane do SVG @ 675 DPI
   - Ekstrakcja placeholders: `product_name`, `ingredients`, `sku`

2. **Generate Labels** (Async)
   - 92 produkty z CSV
   - Formatowanie tekstu (auto-wrap, optimal font size)
   - Output: SVG + PNG + PDF + JPG
   - ZIP: `labels_YYYYMMDD_HHMMSS.zip`
   - Czas: ~2 minuty

3. **Upload Vial Image** (PNG/JPG)
   - Obraz produktu (fiolka)
   - Opcjonalnie: crop region dla label

4. **Generate Mockups** (Async - NOWE!)
   - Parallel processing (4 workers)
   - Dla każdej label:
     - Add green background (#00FF00)
     - Send to Gemini Vision API
     - Remove green background
     - Verification (side-by-side)
     - Retry (max 3×) jeśli failed
   - Output: `mockup_SKU.png`
   - ZIP: `mockups_YYYYMMDD_HHMMSS.zip`
   - Czas: ~15-20 minut (91 mockups)
   - **✅ Możesz przełączyć kartę w Chrome!**

5. **Download All**
   - Combined ZIP: `combined_YYYYMMDD_HHMMSS.zip`
   - Struktura:
     ```
     YPB.100/
       ├── label.svg
       ├── label.png
       ├── label.jpg
       ├── label.pdf
       └── mockup.png
     ```

---

## 🐛 ZNANE PROBLEMY

### AI Converter - Background Loss
**Problem**: AI converter usuwa background rectangles podczas konwersji AI → SVG

**Przyczyna**: Regex `svg = re.sub(r'<use[^>]*xlink:href="#g[0-9]+"[^>]*/>', '', svg)` usuwa również background graphics

**Status**: Known issue, nie naprawione (wymaga refactor AI converter)

**Workaround**: Używaj SVG templates zamiast AI files, lub dodaj background ręcznie

---

## 📈 STATYSTYKI

- **Kod Python**: ~7,800 linii
- **Frontend**: 368 KB (app_dashboard.html)
- **Database**: 92 produkty (YPB.100 - YPB.283)
- **Output total**: ~1.1 GB (archiwum)
- **Avg label generation**: 2 minuty
- **Avg mockup generation**: 15-20 minut (91 mockups, parallel)
- **Verification accuracy**: 96% (side-by-side)

---

## 🔧 MAINTENANCE

### Auto-cleanup
- Startup cleanup: usuwa pliki >24h z `temp/` i `output/`
- Wykonywane przy każdym starcie aplikacji

### Manual cleanup
```python
from cleanup_utils import cleanup_old_files
cleanup_old_files(config.TEMP_DIR, hours=24)
cleanup_old_files(config.OUTPUT_DIR, hours=24)
```

---

## 📝 CHANGELOG

### 31 stycznia 2026
- ✅ **Async Mockup Generation** - możliwość przełączania kart
- ✅ Flask `threaded=True`
- ✅ Background tasks z `@run_in_background`
- ✅ JavaScript polling (500ms)
- ✅ Progress tracking w czasie rzeczywistym

### 30 stycznia 2026
- ✅ Side-by-side verification (Gemini Vision API)
- ✅ 96% accuracy (było: 70%)
- ✅ Composite image (mockup | label)

### 29 stycznia 2026
- ✅ Gemini API modernizacja (`google-genai>=1.47.0`)
- ✅ Auto-retry logic (3 attempts)
- ✅ Improved text wrapping (ingredients)
- ✅ Download All button (combined ZIP)

### 28 stycznia 2026
- ✅ Initial deployment
- ✅ Complete application analysis

---

## 🎓 DOKUMENTACJA

- `README.md` - Overview
- `QUICKSTART.md` - Quick start guide
- `START_APP.md` - Startup instructions
- `INSTALL_CAIRO.md` - Cairo installation (macOS)
- `MIGRATION_GUIDE.md` - Gemini SDK migration
- `RAILWAY_DEPLOYMENT.md` - Railway deployment guide

---

## 📞 CONTACT & SUPPORT

**Repository**: https://github.com/lumizone/Ypb
**Application**: Local development (http://localhost:8000)
**Python**: 3.9+
**Platform**: macOS (tested), Linux (compatible)

---

**Last Updated**: 31 stycznia 2026
**Status**: ✅ Production Ready with Async Support
