# YPB Label Generator - Documentation

**Ostatnia aktualizacja:** 29 stycznia 2026 - Modernizacja Gemini API

This folder contains backup documentation files. The main user manual is now embedded directly in the Instructions tab of the application.

## System Overview

The Label Generator is an AI-powered system for creating product labels and mockups:

1. **Label Generation** - Uses intelligent text wrapping algorithm to format text within defined areas (limits)
2. **Mockup Generation** - Uses Google Gemini API (google-genai SDK) to create photorealistic product mockups
3. **Database Management** - CSV-based product database with Product, Ingredients, SKU columns
4. **Archive** - Automatic storage and organization of generated files

## Recent Updates (29.01.2026)

### Mockup Generator Modernization
- ✅ Migrated from `google-generativeai==0.8.6` (deprecated) to `google-genai>=1.47.0`
- ✅ All 4 mockup endpoints updated to new SDK
- ✅ Added auto-retry logic (MAX_RETRIES = 3)
- ✅ Added AI verification for mockup quality
- ✅ Reduced code complexity (67% reduction in `/api/generate-mockup`)
- ✅ Fixed 400 errors from Gemini API

## Key Concepts

### Text Areas (Limits)
Limits are rectangular areas drawn on the template that define:
- Where text should be placed
- How wide lines can be (determines text wrapping)
- How tall the text area is (determines line spacing)

The text wrapping algorithm uses these limits to calculate optimal line breaks and font sizing.

### Processing Pipeline
1. Parse SVG template
2. Extract text elements
3. Apply text wrapping algorithm within limits
4. Replace text with product data
5. Generate output files (SVG, PNG, PDF)
6. Create mockups using Gemini API

## Documentation Files

### Main Documentation
- **README.md** - Main project overview and features (root directory)
- **CLAUDE.md** - Comprehensive system analysis and architecture
- **CHANGELOG.md** - Version history and updates
- **MIGRATION_GUIDE.md** - SDK migration guide (google-generativeai → google-genai)

### Quick Start Guides
- **QUICKSTART.md** - Quick start guide
- **START_APP.md** - How to start the application
- **INSTALL_CAIRO.md** - Cairo installation instructions
- **AUTH_SETUP.md** - Authentication setup

### Technical Documentation (`/backup_settings/`)
- **MOCKUP_GENERATION.md** - Mockup generation with Gemini API (updated 29.01.2026)
- **MODEL_CHANGE_LOG.md** - Gemini model changes and SDK migration
- **API_ENDPOINTS.md** - Complete API reference (updated 29.01.2026)
- **TEXT_FORMATTING.md** - Text wrapping algorithm
- **TEMPLATE_PARSING.md** - Template parsing logic
- **DATABASE_MANAGEMENT.md** - CSV database management
- **BATCH_PROCESSING.md** - Batch processing system

## For Developers

### SDK Migration (29.01.2026)
Read **MIGRATION_GUIDE.md** for complete guide on migrating from old REST API to new google-genai SDK.

### API Reference
See **backup_settings/API_ENDPOINTS.md** for complete list of endpoints with request/response examples.

### Mockup Generation
See **backup_settings/MOCKUP_GENERATION.md** for detailed documentation of:
- New SDK usage (google-genai)
- Retry logic pattern
- AI verification system
- Green screen removal
- All 4 mockup endpoints
