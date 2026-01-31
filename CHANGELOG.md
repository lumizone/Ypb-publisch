# Changelog - YPB Label Generator

All notable changes to this project are documented in this file.

---

## [2.0.0] - 2026-01-29 - Modernizacja Gemini API

### 🚀 Major Update: SDK Migration

Migrated from deprecated `google-generativeai==0.8.6` to new official SDK `google-genai>=1.47.0`

### ✅ Updated Endpoints

All 4 mockup generation endpoints modernized:

#### 1. `/api/generate-single-mockup`
- ✅ Migrated to new SDK
- ✅ Added auto-retry logic (MAX_RETRIES = 3)
- ✅ Added AI verification

#### 2. `/api/generate-mockups-from-labels`
- ✅ Migrated to new SDK
- ✅ Added auto-retry logic
- ✅ Added AI verification
- ✅ Parallel processing with ThreadPoolExecutor
- ✅ Thread-safe progress tracking

#### 3. `/api/generate-mockup`
**ZAKTUALIZOWANY 29.01.2026**
- ✅ Migrated from REST API to new SDK
- ✅ Added auto-retry logic (MAX_RETRIES = 3)
- ✅ Added AI verification
- ✅ Reduced code from ~360 lines to ~120 lines (67% reduction)

#### 4. `/api/generate-batch-mockups`
**ZAKTUALIZOWANY 29.01.2026**
- ✅ Migrated to new SDK
- ✅ Added auto-retry logic for each product
- ✅ Added AI verification
- ⚠️ Sequential processing (parallel może być dodane w przyszłości)

### 🔧 New Features

#### Auto-Retry Logic
```python
MAX_RETRIES = 3
for attempt in range(1, MAX_RETRIES + 1):
    mockup = generate_mockup(...)
    if verify(mockup):
        break
    # Retry with error hints from previous attempt
```

#### AI Verification
- New function: `_verify_mockup_with_vision()`
- Verifies SKU, product name, and dosage on mockups
- Uses Gemini Vision API for OCR verification
- Returns errors that are used as retry hints

#### Retry Hints
- Errors from previous attempts are passed to Gemini
- Example: "PREVIOUS ATTEMPT FAILED. Errors: SKU mismatch, dosage incorrect"
- Helps AI correct mistakes in subsequent attempts

### 📦 Package Changes

**requirements.txt:**
```diff
- google-generativeai>=0.8.6
+ google-genai>=1.47.0
```

### 🔄 API Changes

**Before (REST API):**
```python
import requests
url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-image:generateContent?key={key}"
response = requests.post(url, json=payload)
```

**After (New SDK):**
```python
from google import genai
from google.genai import types

client = genai.Client(api_key=config.GEMINI_API_KEY)
response = client.models.generate_content(
    model='gemini-2.5-flash-image',
    contents=[prompt, vial_image, label_image],
    config=generation_config
)
```

### 📊 Benefits

1. **No manual base64 encoding** - SDK handles image conversion
2. **Direct PIL.Image support** - Pass images directly
3. **Better error handling** - Structured exceptions
4. **Official SDK** - Aligned with Google's 2026 documentation
5. **Cleaner code** - 67% reduction in `/api/generate-mockup`

### 🐛 Fixed

- Fixed 400 errors from Gemini API (deprecated REST API)
- Fixed image extraction errors (`'Image' object has no attribute 'mode'`)
- Improved mockup quality with retry and verification

### 📝 Documentation Updates

Updated files:
- ✅ `CLAUDE.md` - Added comprehensive modernization section
- ✅ `backup_settings/MOCKUP_GENERATION.md` - Updated to new SDK
- ✅ `backup_settings/MODEL_CHANGE_LOG.md` - Added SDK migration entry
- ✅ `backup_settings/API_ENDPOINTS.md` - Updated endpoint documentation
- ✅ `README.md` - Added mockup features and API requirements
- ✅ `CHANGELOG.md` - This file

---

## [1.3.0] - 2026-01-28 - Text Wrapping Improvements

### 🔧 Improved

#### Balanced Text Wrapping
- Enhanced `_balanced_wrap()` function in `text_formatter.py`
- Even distribution algorithm for ingredients separated by "/"
- Example: 4 ingredients → 2:2 distribution (instead of 1:3)

**Algorithm:**
```python
base_groups_per_line = num_groups // num_lines
extra_groups = num_groups % num_lines

for line_num in range(num_lines):
    groups_for_this_line = base_groups_per_line
    if line_num < extra_groups:
        groups_for_this_line += 1
```

### 📊 Example

**Before:**
```
GHRP-2 (5mg) /
Tesamorelin 5mg / MGF 500mcg / Ipamorelin 2.5mg
```

**After:**
```
GHRP-2 (5mg) / Tesamorelin 5mg /
MGF 500mcg / Ipamorelin 2.5mg
```

---

## [1.2.0] - 2026-01-23 - Model Rollback

### 🔄 Changed

- Rolled back from `gemini-3-pro-image-preview` to `gemini-2.5-flash-image`
- Reason: User preference (faster, cheaper)

---

## [1.1.0] - 2026-01-22 - Model Upgrade

### 🚀 Changed

- Upgraded to `gemini-3-pro-image-preview` for better mockup quality
- Improved color preservation
- Better positioning accuracy

---

## [1.0.0] - Initial Release

### ✨ Features

- Label generation from SVG/AI templates
- CSV database integration
- Batch processing (60-100+ products)
- Multi-format output (SVG, PNG 300 DPI, PDF vector)
- Mockup generation with Gemini API
- Green screen background removal
- ZIP packaging and delivery
- Progress tracking
- Database management
- Web interface (Flask)

### 🏗️ Architecture

- Python 3.8+
- Flask web framework
- Cairo/Inkscape for rendering
- Google Gemini API for mockups
- Thread-safe batch processing

---

## Legend

- 🚀 Major Update
- ✨ New Feature
- 🔧 Improved
- 🐛 Fixed
- 🔄 Changed
- 📝 Documentation
- 📦 Dependencies
- ⚠️ Deprecated
