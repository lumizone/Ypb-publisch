"""Configuration settings for the Label Replication System."""

import os
from pathlib import Path

# Load environment variables from .env.local if it exists
try:
    from dotenv import load_dotenv
    env_local = Path(__file__).parent / '.env.local'
    if env_local.exists():
        load_dotenv(env_local, override=True)
        print(f"Loaded .env.local from {env_local}")
    else:
        print(f".env.local not found at {env_local}")
except ImportError:
    print("Warning: python-dotenv not installed. Install it with: pip install python-dotenv")
except Exception as e:
    print(f"Warning: Error loading .env.local: {e}")

# Base directory
BASE_DIR = Path(__file__).parent

# Storage directory (use Railway volume if available, otherwise local)
# Railway volumes are persistent across deployments
if Path("/data").exists() and os.environ.get('RAILWAY_ENVIRONMENT'):
    STORAGE_DIR = Path("/data")
    print(f"Using Railway persistent volume: {STORAGE_DIR}")
else:
    STORAGE_DIR = BASE_DIR
    print(f"Using local storage: {STORAGE_DIR}")

# Temporary file storage
TEMP_DIR = STORAGE_DIR / "temp"
TEMP_DIR.mkdir(exist_ok=True)

OUTPUT_DIR = STORAGE_DIR / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

UPLOAD_DIR = STORAGE_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

DATABASES_DIR = BASE_DIR / "databases"  # Always use local (in git repo)
DATABASES_DIR.mkdir(exist_ok=True)

# Required placeholders in template
REQUIRED_PLACEHOLDERS = ["product_name", "ingredients", "sku", "cas", "mw"]

# Export settings
PNG_DPI = 2400
PDF_VECTOR_MODE = True

# Batch processing
MAX_BATCH_SIZE = 1000
MAX_CONCURRENT_JOBS = 4

# File size limits (MB)
MAX_TEMPLATE_SIZE = 50
MAX_CSV_SIZE = 10

# Supported file formats
SUPPORTED_TEMPLATE_FORMATS = [".ai", ".svg", ".pdf"]
SUPPORTED_DATA_FORMATS = [".csv"]

# Cleanup settings
AUTO_CLEANUP_HOURS = 24

# AI API settings
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY', '') or os.getenv('OPEN_AI_API_KEY', '')
ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY', '') or os.getenv('CLAUDE_API_KEY', '')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', '')

# Debug: Print if GEMINI_API_KEY is loaded (without showing the key)
if GEMINI_API_KEY:
    print(f"GEMINI_API_KEY loaded: {'*' * min(len(GEMINI_API_KEY), 20)}")
else:
    print("GEMINI_API_KEY not found in environment variables")

AI_DEFAULT_MODEL = os.getenv('AI_DEFAULT_MODEL', 'openai')  # 'openai' or 'anthropic'
AI_ENABLED = bool(OPENAI_API_KEY or ANTHROPIC_API_KEY)

# Gemini model for mockup generation
GEMINI_MOCKUP_MODEL = os.getenv('GEMINI_MOCKUP_MODEL', 'gemini-2.5-flash-image')

# Unified Gemini API generation settings for mockups
# These settings control creativity vs accuracy tradeoff
GEMINI_MOCKUP_CONFIG = {
    "responseModalities": ["IMAGE"],
    "temperature": 0.1,      # Low = more accurate, less creative
    "topP": 0.85,            # Focus on most likely outputs
    "topK": 10               # Limit randomness
}

# Stricter settings for retry attempts (when first attempt had errors)
GEMINI_MOCKUP_CONFIG_RETRY = {
    "responseModalities": ["IMAGE"],
    "temperature": 0.05,     # Even lower for corrections
    "topP": 0.9,             # More focused
    "topK": 5                # Much tighter sampling
}
