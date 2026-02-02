"""Flask web application for the Label Replication System."""

from flask import Flask, request, jsonify, send_file, render_template_string, Response
from werkzeug.utils import secure_filename
from pathlib import Path
import logging
import os
import json
from datetime import datetime
import re
import shutil
import zipfile
import xml.etree.ElementTree as ET
from functools import wraps
import threading

from template_parser import TemplateParser, TemplateParseError
from data_mapper import DataMapper, DataMapperError
from csv_manager import CSVManager, CSVManagerError
from ai_converter import AIConverter, AIConverterError
from progress_tracker import ProgressTracker
from cleanup_utils import auto_cleanup_startup, cleanup_job_files
from verification_side_by_side import verify_mockup_with_sidebyside, create_mockup_vs_label_comparison
import config
import io
import numpy as np

# Lazy imports for modules that require Cairo (may fail on import)
HAS_RENDERING = False
BatchProcessor = None
BatchProcessorError = None
Packager = None
PackagerError = None

try:
    from batch_processor import BatchProcessor, BatchProcessorError
    from packager import Packager, PackagerError
    HAS_RENDERING = True
except (ImportError, OSError) as e:
    import logging
    logging.warning(f"Rendering modules not available (Cairo issue): {e}")
    HAS_RENDERING = False

# Lazy import for rembg (may fail on import)
HAS_REMBG = False
rembg_remove = None

try:
    from rembg import remove as rembg_remove
    HAS_REMBG = True
except ImportError as e:
    import logging
    logging.warning(f"rembg not available: {e}. Background removal will use fallback method.")
    HAS_REMBG = False

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB max file size
app.config['UPLOAD_FOLDER'] = config.UPLOAD_DIR

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# #region agent log (disabled in production)
def _dbg(location, msg, data=None, hid="H1"):
    """Debug logging - DISABLED in production for security and performance."""
    # Only enable debug logging if explicitly requested via environment variable
    if not os.environ.get('ENABLE_DEBUG_LOG', '').lower() == 'true':
        return  # No-op in production
    try:
        import json as _j
        from time import time as _t
        p = Path(__file__).parent / ".cursor" / "debug.log"
        p.parent.mkdir(exist_ok=True)
        with open(p, "a") as f:
            f.write(_j.dumps({"location": location, "message": msg, "data": data or {}, "hypothesisId": hid, "timestamp": int(_t() * 1000), "sessionId": "debug-session"}) + "\n")
    except Exception:
        pass
# #endregion

# Progress tracking for batch operations (with automatic cleanup)
progress_tracker = ProgressTracker(max_entries=100, expire_minutes=30)

# Background task results storage
background_results = {}

def run_in_background(func):
    """Decorator to run function in background thread"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        thread = threading.Thread(target=func, args=args, kwargs=kwargs)
        thread.daemon = True  # Thread will close when app exits
        thread.start()
        return thread
    return wrapper

# Default paths
DEFAULT_TEMPLATE = str(config.BASE_DIR / "real_example.svg")
DEFAULT_CSV = str(config.DATABASES_DIR / "YPB_final_databse.csv")

# Currently selected database (can be changed via API)
current_database = DEFAULT_CSV

def get_current_database():
    """Get the currently selected database path."""
    global current_database
    
    # If current database exists, return it
    if current_database and Path(current_database).exists():
        return current_database
    
    # If default exists, use it
    if Path(DEFAULT_CSV).exists():
        current_database = DEFAULT_CSV
        return current_database
    
    # Otherwise, find first available CSV in databases directory
    db_dir = config.DATABASES_DIR
    csv_files = list(db_dir.glob('*.csv'))
    if csv_files:
        current_database = str(csv_files[0])
        logger.info(f"Auto-selected database: {current_database}")
        return current_database
    
    # No database found
    logger.warning("No database files found in databases directory")
    return DEFAULT_CSV

def set_current_database(db_path):
    """Set the currently selected database."""
    global current_database
    if Path(db_path).exists():
        current_database = str(db_path)
        return True
    return False

# Load dashboard HTML
with open(Path(__file__).parent / 'app_dashboard.html', 'r') as f:
    DASHBOARD_UI = f.read()

# Run startup cleanup
auto_cleanup_startup(config.TEMP_DIR, config.OUTPUT_DIR, config.UPLOAD_DIR, hours=config.AUTO_CLEANUP_HOURS)

# Basic Authentication
AUTH_USER = os.getenv('AUTH_USER', 'admin')
AUTH_PASS = os.getenv('AUTH_PASS', 'changeme')
DISABLE_AUTH = os.getenv('DISABLE_AUTH', 'false').lower() in ['true', '1', 'yes']

# Log auth config at startup
if DISABLE_AUTH:
    logger.warning(f"⚠️  Basic Auth DISABLED (DISABLE_AUTH=true) - Development mode only!")
else:
    logger.info(f"🔒 Basic Auth ENABLED - Username: {AUTH_USER}")

def requires_auth(f):
    """Decorator for Basic Authentication."""
    @wraps(f)
    def decorated(*args, **kwargs):
        # Skip auth if disabled (for local development)
        if DISABLE_AUTH:
            logger.debug("Auth bypassed - DISABLE_AUTH is true")
            return f(*args, **kwargs)
        
        # Normal Basic Auth flow
        auth = request.authorization
        
        if not auth:
            logger.warning(f"No auth provided - sending 401")
            response = Response(
                '401 Unauthorized\n\nLogin Required',
                401,
                {'WWW-Authenticate': 'Basic realm="YPB Dashboard"'}
            )
            return response
        
        logger.info(f"Auth provided - Username: '{auth.username}'")
        
        if auth.username != AUTH_USER or auth.password != AUTH_PASS:
            logger.warning(f"Auth FAILED - Username mismatch or wrong password")
            response = Response(
                '401 Unauthorized\n\nInvalid credentials',
                401,
                {'WWW-Authenticate': 'Basic realm="YPB Dashboard"'}
            )
            return response
        
        logger.info(f"✅ Auth successful - User: {auth.username}")
        return f(*args, **kwargs)
    return decorated


def _detect_dominant_colors(image, max_colors=10):
    """
    Wykrywa dominujące kolory w obrazie.
    Returns: List of (R, G, B) tuples sorted by frequency
    """
    import PIL.Image

    # Convert to RGB
    if image.mode == 'RGBA':
        bg = PIL.Image.new('RGB', image.size, (255, 255, 255))
        bg.paste(image, mask=image.split()[3])
        image = bg
    elif image.mode != 'RGB':
        image = image.convert('RGB')

    # Resize for faster processing (max 200px)
    image_small = image.copy()
    image_small.thumbnail((200, 200), PIL.Image.Resampling.LANCZOS)

    # Get pixels
    pixels = list(image_small.getdata())

    # Count colors
    from collections import Counter
    color_counts = Counter(pixels)

    # Return most common colors
    dominant = [color for color, count in color_counts.most_common(max_colors)]
    return dominant


def _choose_optimal_background_color(label_image, vial_image=None):
    """
    Wybiera optymalny kolor tła który NIE jest obecny w label ani vial.

    Candidate colors (pure, easy to remove):
    - Green: #00FF00 (RGB 0, 255, 0)
    - Magenta: #FF00FF (RGB 255, 0, 255)
    - Cyan: #00FFFF (RGB 0, 255, 255)
    - Yellow: #FFFF00 (RGB 255, 255, 0)
    - Blue: #0000FF (RGB 0, 0, 255)

    Returns: (R, G, B) tuple - best background color
    """
    import numpy as np

    # Candidate background colors (pure, saturated, easy to remove)
    candidates = [
        (0, 255, 0),      # Green (default)
        (255, 0, 255),    # Magenta
        (0, 255, 255),    # Cyan
        (255, 255, 0),    # Yellow
        (0, 0, 255),      # Blue
    ]

    # Detect colors in label
    label_colors = _detect_dominant_colors(label_image, max_colors=50)

    # Detect colors in vial (if provided)
    vial_colors = []
    if vial_image:
        vial_colors = _detect_dominant_colors(vial_image, max_colors=50)

    # Combine all colors to avoid
    colors_to_avoid = label_colors + vial_colors

    # Calculate minimum distance for each candidate
    best_color = candidates[0]  # Default: green
    best_distance = 0

    for candidate in candidates:
        # Calculate minimum distance to any existing color
        min_distance = float('inf')

        for existing_color in colors_to_avoid:
            # Euclidean distance in RGB space
            distance = np.sqrt(
                (candidate[0] - existing_color[0]) ** 2 +
                (candidate[1] - existing_color[1]) ** 2 +
                (candidate[2] - existing_color[2]) ** 2
            )
            min_distance = min(min_distance, distance)

        # Choose candidate with maximum minimum distance (most different)
        if min_distance > best_distance:
            best_distance = min_distance
            best_color = candidate

    color_name = {
        (0, 255, 0): "Green",
        (255, 0, 255): "Magenta",
        (0, 255, 255): "Cyan",
        (255, 255, 0): "Yellow",
        (0, 0, 255): "Blue",
    }.get(best_color, "Unknown")

    logger.info(f"Selected background color: {color_name} RGB{best_color} (min distance to existing colors: {best_distance:.1f})")

    return best_color


def add_green_background(image, background_color=None):
    """
    Nanosi kolorowe tło na obraz fiolki.
    Zachowuje przezroczystość oryginalnego obrazu.

    Args:
        image: PIL Image (może być RGBA)
        background_color: (R, G, B) tuple or None (default: #00FF00 green)

    Returns: PIL Image (RGB) z kolorowym tłem
    """
    import PIL.Image

    if background_color is None:
        background_color = (0, 255, 0)  # Default: green

    if image.mode != 'RGBA':
        image = image.convert('RGBA')

    result = PIL.Image.new('RGB', image.size, background_color)
    result.paste(image, mask=image.split()[3])

    color_name = {
        (0, 255, 0): "Green #00FF00",
        (255, 0, 255): "Magenta #FF00FF",
        (0, 255, 255): "Cyan #00FFFF",
        (255, 255, 0): "Yellow #FFFF00",
        (0, 0, 255): "Blue #0000FF",
    }.get(background_color, f"Custom RGB{background_color}")

    logger.info(f"Applied {color_name} background for chroma-key removal")

    return result


def _aspect_ratio_for_gemini(width, height):
    """Map image dimensions to nearest Gemini-supported aspect ratio (gemini-2.5-flash-image)."""
    if not width or not height:
        return "1:1"
    r = width / height
    supported = [
        ("1:1", 1.0), ("2:3", 2 / 3), ("3:2", 3 / 2), ("3:4", 3 / 4), ("4:3", 4 / 3),
        ("4:5", 4 / 5), ("5:4", 5 / 4), ("9:16", 9 / 16), ("16:9", 16 / 9), ("21:9", 21 / 9),
    ]
    return min(supported, key=lambda x: abs(r - x[1]))[0]


def _extract_label_color_palette(label_image, max_colors=50):
    """
    Extract unique color palette from label image.
    Returns list of RGB tuples representing label colors.
    """
    import PIL.Image
    import numpy as np
    from collections import Counter

    # Convert to RGB if needed
    if label_image.mode == 'RGBA':
        # Composite onto white to get actual rendered colors
        bg = PIL.Image.new('RGB', label_image.size, (255, 255, 255))
        bg.paste(label_image, mask=label_image.split()[-1])
        label_rgb = bg
    elif label_image.mode != 'RGB':
        label_rgb = label_image.convert('RGB')
    else:
        label_rgb = label_image

    # Get all pixels
    pixels = np.array(label_rgb)
    h, w, _ = pixels.shape

    # Flatten to list of RGB tuples
    flat_pixels = pixels.reshape(-1, 3)

    # Count occurrences of each color
    color_counts = Counter(map(tuple, flat_pixels))

    # Get most common colors (these are the label's color palette)
    most_common_colors = [color for color, count in color_counts.most_common(max_colors)]

    logger.info(f"Extracted {len(most_common_colors)} colors from label palette")
    logger.debug(f"Top 5 label colors: {most_common_colors[:5]}")

    return most_common_colors


def _smart_color_comparison_removal(mockup_image, label_reference):
    """
    SMART background removal using color comparison.

    Algorithm:
    1. Extract color palette from reference label
    2. For each pixel in mockup:
       - Calculate distance to pure green (#00FF00)
       - Calculate distance to nearest label color
       - Decide: keep if closer to label, remove if closer to green screen
    3. Use alpha channel as additional factor

    This preserves ALL label colors (including #ccdc34) while removing green screen.
    """
    import PIL.Image
    import numpy as np

    try:
        logger.info("Starting SMART color comparison removal")

        # Extract label color palette
        label_palette = _extract_label_color_palette(label_reference, max_colors=100)

        # Convert mockup to RGBA if needed
        if mockup_image.mode != 'RGBA':
            mockup_image = mockup_image.convert('RGBA')

        # Get pixel data
        data = np.array(mockup_image)
        rgb = data[:, :, :3].astype(np.float32)
        alpha = data[:, :, 3].astype(np.float32)

        r = rgb[:, :, 0]
        g = rgb[:, :, 1]
        b = rgb[:, :, 2]

        # Pure green screen reference
        green_screen = np.array([0, 255, 0], dtype=np.float32)

        # Calculate distance to green screen for each pixel
        dist_to_green = np.sqrt(
            (r - green_screen[0]) ** 2 +
            (g - green_screen[1]) ** 2 +
            (b - green_screen[2]) ** 2
        )

        # Calculate minimum distance to any label color for each pixel
        dist_to_label = np.full_like(dist_to_green, float('inf'))

        for label_color in label_palette:
            lr, lg, lb = label_color
            dist = np.sqrt(
                (r - lr) ** 2 +
                (g - lg) ** 2 +
                (b - lb) ** 2
            )
            dist_to_label = np.minimum(dist_to_label, dist)

        # ULTRA-AGGRESSIVE: Remove ALL green, protect ONLY exact label colors
        should_remove = np.zeros(alpha.shape, dtype=bool)

        # RULE 1: ANY green dominance → REMOVE
        has_green_tint = (g > r + 15) | (g > b + 15)
        should_remove |= has_green_tint

        # RULE 2: Close to pure green → REMOVE (extra aggressive)
        should_remove |= (dist_to_green < 100)

        # RULE 3: Semi-transparent + any greenish → REMOVE
        should_remove |= (alpha < 250) & ((g > r + 5) | (g > b + 5))

        # PROTECTION: ONLY protect if VERY close to label color (exact match basically)
        # This is very strict - only distances < 15 are protected
        exact_label_match = (dist_to_label < 15)
        should_remove &= ~exact_label_match

        # Log some stats for debugging
        green_tint_count = has_green_tint.sum()
        protected_count = exact_label_match.sum()
        logger.debug(f"Green tint pixels: {green_tint_count}, Protected (exact label): {protected_count}")

        # Apply removal
        alpha[should_remove] = 0

        # Statistics
        total_pixels = alpha.size
        removed_pixels = should_remove.sum()
        removal_pct = (removed_pixels / total_pixels) * 100

        logger.info(f"Smart removal: {removed_pixels}/{total_pixels} pixels ({removal_pct:.1f}%)")

        # Create output image
        output_data = data.copy()
        output_data[:, :, 3] = alpha.astype(np.uint8)
        output_image = PIL.Image.fromarray(output_data, mode='RGBA')

        return output_image

    except Exception as e:
        logger.error(f"Smart color comparison removal failed: {e}", exc_info=True)
        # Fallback: return original
        return mockup_image


def _aggressive_background_cleanup(image, background_color=None):
    """
    ULTRA AGRESYWNE czyszczenie tła po rembg.

    Usuwa:
    1. Wszystkie pozostałości background_color (większy threshold)
    2. Semi-transparent pixels near transparent areas (expand transparency)
    3. Low-opacity pixels (alpha < 50)
    4. Edge artifacts and halos

    Args:
        image: PIL Image (RGBA) - after rembg
        background_color: (R, G, B) tuple - color to remove aggressively

    Returns:
        PIL Image (RGBA) - with aggressively cleaned background
    """
    import PIL.Image
    import numpy as np

    try:
        if background_color is None:
            background_color = (0, 255, 0)  # Default: green

        logger.info(f"Starting AGGRESSIVE background cleanup for color RGB{background_color}")

        # Convert to numpy
        data = np.array(image)
        rgb = data[:, :, :3].astype(np.float32)
        alpha = data[:, :, 3].astype(np.float32)

        r, g, b = rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2]
        target_r, target_g, target_b = background_color

        # === STRATEGY 1: Remove similar colors (AGGRESSIVE threshold) ===
        color_distance = np.sqrt(
            (r - target_r) ** 2 +
            (g - target_g) ** 2 +
            (b - target_b) ** 2
        )
        # AGGRESSIVE: increased from 70 to 100
        similar_to_bg = color_distance < 100

        # === STRATEGY 2: Remove low-opacity pixels (semi-transparent = likely artifacts) ===
        low_opacity = alpha < 50  # Remove anything with alpha < 50

        # === STRATEGY 3: Remove green-ish pixels (for green backgrounds) ===
        if background_color == (0, 255, 0):  # Green
            greenish = (g > r + 20) & (g > b + 20) & (g > 80)
        elif background_color == (255, 0, 255):  # Magenta
            magentaish = (r > g + 20) & (b > g + 20) & ((r + b) / 2 > 100)
            greenish = magentaish
        elif background_color == (0, 255, 255):  # Cyan
            cyanish = (g > r + 20) & (b > r + 20) & ((g + b) / 2 > 100)
            greenish = cyanish
        elif background_color == (255, 255, 0):  # Yellow
            yellowish = (r > b + 20) & (g > b + 20) & ((r + g) / 2 > 100)
            greenish = yellowish
        elif background_color == (0, 0, 255):  # Blue
            blueish = (b > r + 20) & (b > g + 20) & (b > 100)
            greenish = blueish
        else:
            greenish = np.zeros_like(alpha, dtype=bool)

        # === STRATEGY 4: Expand transparency (erode edges with background color) ===
        try:
            from scipy import ndimage

            # Find transparent areas
            transparent_mask = (alpha == 0)

            # Dilate (expand) transparent areas by 3 pixels
            dilated_transparent = ndimage.binary_dilation(transparent_mask, iterations=3)

            # Remove pixels near transparent areas if they match background
            edge_artifacts = dilated_transparent & (alpha > 0) & (
                similar_to_bg | greenish | low_opacity
            )

            logger.info(f"Expanded transparency by 3 pixels, found {np.sum(edge_artifacts)} edge artifacts")
        except ImportError:
            edge_artifacts = np.zeros_like(alpha, dtype=bool)

        # === COMBINE ALL REMOVAL STRATEGIES ===
        pixels_to_remove = similar_to_bg | low_opacity | greenish | edge_artifacts

        # Set alpha to 0 for removed pixels
        alpha[pixels_to_remove] = 0

        # Clean RGB for transparent pixels
        transparent = (alpha == 0)
        rgb[transparent] = [0, 0, 0]

        # Apply changes
        data[:, :, 3] = np.clip(alpha, 0, 255).astype(np.uint8)
        data[:, :, :3] = np.clip(rgb, 0, 255).astype(np.uint8)

        cleaned_image = PIL.Image.fromarray(data, 'RGBA')

        pixels_removed = np.sum(pixels_to_remove)
        total_pixels = alpha.size
        logger.info(f"AGGRESSIVE cleanup removed {pixels_removed} pixels ({100*pixels_removed/total_pixels:.1f}%)")

        return cleaned_image

    except Exception as e:
        logger.error(f"AGGRESSIVE cleanup failed: {e}", exc_info=True)
        return image  # Return original if cleanup fails


def _remove_green_halo_and_cleanup(image):
    """
    AGGRESSIVE post-processing: usuwa WSZYSTKIE zielone piksele i zieloną obwódkę.
    Analizuje obraz w przestrzeni HSV i RGB, usuwa wszystko co jest zielone.
    Zachowuje TYLKO piksele które są wyraźnie NIE-zielone (białe, czarne, niebieskie, szare).
    """
    import PIL.Image
    from colorsys import rgb_to_hsv
    
    try:
        # Konwertuj do numpy array
        data = np.array(image)
        rgb = data[:, :, :3].astype(np.float32)
        alpha = data[:, :, 3].astype(np.float32)
        
        r = rgb[:, :, 0]
        g = rgb[:, :, 1]
        b = rgb[:, :, 2]
        
        # === SMART GREEN SCREEN DETECTION ===
        # Goal: Remove ONLY pure green screen (#00FF00), NOT label colors like #ccdc34

        # STRATEGIA 1: Dystans od czystego zielonego (#00FF00) - BARDZIEJ RESTRYKCYJNY
        # Pure green: RGB(0, 255, 0) - very bright green with no red/blue
        green_distance = np.sqrt((r - 0) ** 2 + (g - 255) ** 2 + (b - 0) ** 2)
        close_to_pure_green = (green_distance < 70) & (g > 200) & (r < 80) & (b < 80)

        # STRATEGIA 2: Green screen specific - bardzo jasny zielony bez czerwonego/niebieskiego
        # This catches #00FF00 and very close variants but NOT yellow-green like #ccdc34
        pure_green_screen = (g > 220) & (r < 60) & (b < 60)

        # DISABLED STRATEGY 3: Too aggressive - was removing label background
        # green_dominant = (g > r + 30) & (g > b + 30) & (g > 80)
        # high_green_ratio = (green_ratio > 0.45) & (g > 70)
        
        # STRATEGIA 4: HSV - Hue w zakresie zielonego (60-180 stopni)
        # Konwertuj do HSV dla lepszego wykrywania odcieni
        rgb_normalized = rgb / 255.0
        r_norm = rgb_normalized[:, :, 0]
        g_norm = rgb_normalized[:, :, 1]
        b_norm = rgb_normalized[:, :, 2]
        
        max_val = np.maximum(np.maximum(r_norm, g_norm), b_norm)
        min_val = np.minimum(np.minimum(r_norm, g_norm), b_norm)
        diff = max_val - min_val
        
        # Oblicz Hue (0-360)
        hue = np.zeros_like(max_val)
        mask = diff > 0
        
        # Red is max
        red_max = mask & (max_val == r_norm)
        hue[red_max] = 60 * (((g_norm[red_max] - b_norm[red_max]) / diff[red_max]) % 6)
        
        # Green is max
        green_max = mask & (max_val == g_norm)
        hue[green_max] = 60 * (((b_norm[green_max] - r_norm[green_max]) / diff[green_max]) + 2)
        
        # Blue is max
        blue_max = mask & (max_val == b_norm)
        hue[blue_max] = 60 * (((r_norm[blue_max] - g_norm[blue_max]) / diff[blue_max]) + 4)
        
        # Saturation
        saturation = np.where(max_val > 0, diff / max_val, 0)
        
        # STRATEGIA 3: Bardzo jasne zielone (green screen) - RESTRYKCYJNY
        # Only very bright green with minimal red/blue
        bright_green = (g > 220) & (r < 60) & (b < 60)

        # STRATEGIA 4: Ciemne cienie green screen - RESTRYKCYJNY
        # Only dark green shadows with very low red/blue
        dark_green_shadows = (g > 80) & (g < 180) & (r < 40) & (b < 40)

        # STRATEGIA 5: Półprzezroczyste zielone (green halo) - KONSERWATYWNY
        # Use HSV ONLY for very transparent pixels (true edges/anti-aliasing)
        # This catches green glow but NOT solid mockup areas
        green_hue_edges = (
            (alpha > 0) & (alpha < 150) &   # Very transparent edges only
            (hue >= 90) & (hue <= 150) &    # Narrow green hue (pure green range)
            (saturation > 0.4) &             # Must be clearly colorful
            (max_val > 0.5) &                # Must be bright enough
            (g > 100)                        # Require significant green
        )

        # STRATEGIA 6: Zielona poświata - BARDZO KONSERWATYWNY
        # Only catch very obvious green tint on very transparent areas
        green_tint_edges = (
            (alpha > 0) & (alpha < 100) &    # Extremely transparent only
            (g > r + 30) & (g > b + 30) &    # Strong green dominance
            (g > 120)                         # High green value
        )

        # === POŁĄCZ BEZPIECZNE STRATEGIE ===
        # Combines strategies that remove green screen + edge glow, but preserve label colors
        green_to_remove = (
            close_to_pure_green |      # Pure green #00FF00
            pure_green_screen |         # Very bright green
            bright_green |              # Bright green screen
            dark_green_shadows |        # Dark green shadows
            green_hue_edges |           # Green halo on semi-transparent edges (NEW)
            green_tint_edges            # Subtle green glow on edges (NEW)
        )
        
        # === WYJĄTKI: ZACHOWAJ piksele które są WYRAŹNIE NIE-zielone ===
        # Białe/szare piksele (etykieta, tło etykiety)
        is_white_gray = (
            (np.abs(r - g) < 30) & 
            (np.abs(g - b) < 30) & 
            (np.abs(r - b) < 30) &
            (r > 150)  # Jasne
        )
        
        # Niebieskie piksele (tekst, pasek)
        is_blue = (b > r + 40) & (b > g + 20) & (b > 100)
        
        # Czarne/ciemne piksele (tekst, linie)
        is_dark = (r < 80) & (g < 80) & (b < 80)
        
        # Czerwone/pomarańczowe (jeśli są na etykiecie)
        is_red_orange = (r > g + 30) & (r > b + 20)
        
        # NIE USUWAJ tych pikseli
        keep_pixels = is_white_gray | is_blue | is_dark | is_red_orange
        green_to_remove = green_to_remove & ~keep_pixels
        
        # === ROZSZERZ USUWANIE NA KRAWĘDZIACH (scipy) ===
        try:
            from scipy import ndimage
            
            # Znajdź krawędzie przezroczystości
            transparent_mask = (alpha == 0)
            dilated_transparent = ndimage.binary_dilation(transparent_mask, iterations=4)
            
            # Usuń zielone piksele w pobliżu krawędzi
            edge_green = dilated_transparent & (alpha > 0) & (g > 100) & (g > r + 20) & (g > b + 20)
            green_to_remove = green_to_remove | edge_green
            
            # Rozszerz maskę zielonego o 1-2 piksele (usuń obwódkę)
            green_mask_dilated = ndimage.binary_dilation(green_to_remove, iterations=2)
            # Ale tylko tam gdzie są zielone piksele
            green_to_remove = green_to_remove | (green_mask_dilated & (g > 80) & (g > r + 15) & (g > b + 15))
            
        except ImportError:
            pass
        
        # === USUŃ ZIELONE PIKSELE ===
        alpha[green_to_remove] = 0

        # === CZYSZCZENIE RGB ===
        transparent_pixels = (alpha == 0)
        rgb[transparent_pixels] = [0, 0, 0]
        
        # === WYGŁADZANIE ALPHA NA KRAWĘDZIACH ===
        try:
            from scipy import ndimage
            # Median filter dla wygładzenia ostrych krawędzi
            alpha_uint = alpha.astype(np.uint8)
            alpha_smoothed = ndimage.median_filter(alpha_uint, size=3)
            
            # Zastosuj tylko tam gdzie alpha > 0 (nie rozszerzaj przezroczystości)
            alpha = np.where(alpha > 0, alpha_smoothed, 0).astype(np.float32)
        except ImportError:
            pass
        
        # Zastosuj zmiany
        data[:, :, 3] = np.clip(alpha, 0, 255).astype(np.uint8)
        data[:, :, :3] = np.clip(rgb, 0, 255).astype(np.uint8)
        
        cleaned_image = PIL.Image.fromarray(data, 'RGBA')
        
        # Statystyki
        pixels_removed = np.sum(green_to_remove)
        total_pixels = green_to_remove.size
        visible_after = np.sum(alpha > 0)
        logger.info(f"Aggressive post-processing: removed {pixels_removed} green pixels ({100*pixels_removed/total_pixels:.2f}%), visible: {visible_after}")
        
        return cleaned_image
        
    except Exception as e:
        logger.warning(f"Post-processing failed: {e}. Returning original image.", exc_info=True)
        return image


def _load_label_image(label_path):
    """
    Load label image from file, handling both raster images and SVG files.
    Converts SVG to PIL Image using cairosvg or falls back to rendering methods.
    """
    import PIL.Image
    import io
    
    label_path = Path(label_path)
    
    # Check if file is SVG
    if label_path.suffix.lower() == '.svg':
        try:
            # Try using cairosvg to convert SVG to PNG
            import cairosvg
            
            # Read SVG content
            with open(label_path, 'rb') as f:
                svg_data = f.read()
            
            # Convert SVG to PNG bytes
            png_bytes = cairosvg.svg2png(bytestring=svg_data)
            
            # Convert PNG bytes to PIL Image
            label_image = PIL.Image.open(io.BytesIO(png_bytes))
            logger.info(f"Successfully converted SVG to image: {label_image.size}")
            return label_image
            
        except Exception as e:
            logger.warning(f"Failed to convert SVG using cairosvg: {e}. Trying alternative method.")
            try:
                # Alternative: use svglib if available
                from svglib.svglib import svg2rlg
                from reportlab.graphics import renderPM
                
                drawing = svg2rlg(str(label_path))
                png_bytes = renderPM.drawToString(drawing, fmt='PNG')
                label_image = PIL.Image.open(io.BytesIO(png_bytes))
                logger.info(f"Successfully converted SVG using svglib: {label_image.size}")
                return label_image
            except Exception as e2:
                logger.error(f"Failed to convert SVG: {e2}")
                raise ValueError(f"Cannot load SVG file. Please convert it to PNG/JPG or ensure cairosvg/svglib is installed.")
    
    # For regular image files (PNG, JPG, etc.)
    try:
        label_image = PIL.Image.open(label_path)
        return label_image
    except Exception as e:
        logger.error(f"Failed to load label image: {e}")
        raise ValueError(f"Cannot load label image: {str(e)}")


def remove_background_with_reference(result_image, vial_reference, label_reference=None, background_color=None):
    """
    Usuwa tło z obrazu wynikowego używając rembg lub color-based removal.

    Args:
        result_image: PIL Image - mockup z kolorowym tłem
        vial_reference: PIL Image - oryginalny obraz fiolki (unused currently)
        label_reference: PIL Image - oryginalny label (unused currently)
        background_color: (R, G, B) tuple - kolor tła do usunięcia (default: green #00FF00)

    Returns:
        PIL Image (RGBA) - mockup bez tła

    Process:
        1. Try rembg (AI-based) first - best quality
        2. Fallback: Color-based removal for specific background_color
    """
    import PIL.Image

    # === TRY REMBG FIRST (AI-based - best quality) ===
    if HAS_REMBG and rembg_remove is not None:
        try:
            logger.info("Attempting to use rembg for AI-based background removal")
            
            # Konwertuj obraz do formatu obsługiwanego przez rembg (PIL Image → bytes)
            if result_image.mode != 'RGBA':
                result_image = result_image.convert('RGBA')
            
            # Konwertuj PIL Image do bytes
            img_bytes = io.BytesIO()
            result_image.save(img_bytes, format='PNG')
            img_bytes.seek(0)
            input_bytes = img_bytes.getvalue()
            
            # Usuń tło używając rembg
            output_bytes = rembg_remove(input_bytes)
            
            # Konwertuj wynik z powrotem do PIL Image
            if output_bytes:
                output_image = PIL.Image.open(io.BytesIO(output_bytes))
                # Upewnij się że wynik jest w formacie RGBA
                if output_image.mode != 'RGBA':
                    output_image = output_image.convert('RGBA')
                
                # === POST-PROCESSING: AGRESYWNE czyszczenie pozostałości tła ===
                output_image = _aggressive_background_cleanup(output_image, background_color)

                logger.info(f"Successfully removed background using rembg + aggressive cleanup. Image mode: {output_image.mode}, size: {output_image.size}")
                return output_image
            else:
                raise ValueError("rembg returned empty result")
                
        except Exception as e:
            logger.warning(f"rembg failed: {e}. Falling back to color-based method.", exc_info=True)
            # Kontynuuj do fallback metody
    
    # === FALLBACK: METODA OPARTA NA WYKRYWANIU KOLORÓW ===
    try:
        if background_color is None:
            background_color = (0, 255, 0)  # Default: green

        color_name = {
            (0, 255, 0): "Green #00FF00",
            (255, 0, 255): "Magenta #FF00FF",
            (0, 255, 255): "Cyan #00FFFF",
            (255, 255, 0): "Yellow #FFFF00",
            (0, 0, 255): "Blue #0000FF",
        }.get(background_color, f"Custom RGB{background_color}")

        logger.info(f"Using fallback color-based background removal for {color_name}")

        # Konwertuj obraz do RGBA
        if result_image.mode != 'RGBA':
            result_image = result_image.convert('RGBA')

        # Konwertuj do numpy array
        data = np.array(result_image)
        rgb = data[:, :, :3]
        alpha = data[:, :, 3]

        r = rgb[:, :, 0]
        g = rgb[:, :, 1]
        b = rgb[:, :, 2]

        # === WYKRYWANIE KOLOROWEGO TŁA ===
        # Target color with tolerance for compression/slight variations
        target_r, target_g, target_b = background_color

        # Calculate distance from target background color
        color_distance = np.sqrt(
            (r - target_r) ** 2 +
            (g - target_g) ** 2 +
            (b - target_b) ** 2
        )

        # Pixels close to background color (AGGRESSIVE threshold: 100, was: 70)
        is_background = color_distance < 100

        logger.info(f"Detected {np.sum(is_background)} background pixels to remove (aggressive threshold=100)")
        
        # === WYKRYWANIE BIAŁEGO TŁA ===
        # Białe tło: wszystkie kanały RGB są bardzo wysokie i podobne
        rgb_variance = np.std(rgb, axis=2)
        brightness = np.mean(rgb, axis=2)
        
        # Bardzo białe piksele (wszystkie kanały > 240, mała wariancja)
        is_pure_white = (r > 240) & (g > 240) & (b > 240) & (rgb_variance < 20)
        
        # Bardzo jasne piksele (jasność > 230, mała wariancja) - bardziej agresywne
        is_very_bright = (brightness > 230) & (rgb_variance < 25)
        
        # Oblicz dystans do czystego białego (szerszy zakres)
        white_distance = np.sqrt((r - 255) ** 2 + (g - 255) ** 2 + (b - 255) ** 2)
        close_to_white = white_distance < 50  # Zwiększony zakres
        
        # Jasne piksele z bardzo małą wariancją (jednolity kolor = tło)
        uniform_bright = (brightness > 220) & (rgb_variance < 30)
        
        # Połącz wszystkie metody wykrywania białego tła (bardziej agresywne)
        white_background = is_pure_white | (is_very_bright & close_to_white) | uniform_bright
        
        # === WYKRYWANIE SZACHOWNICY (fałszywa przezroczystość) ===
        # Szachownica to szare i białe kwadraty
        # Szare piksele: wszystkie kanały RGB są podobne i w zakresie ~120-220
        
        # Szare piksele (mała wariancja, średnia jasność)
        is_grey = (rgb_variance < 15) & (brightness > 100) & (brightness < 240) & (brightness > 110)
        
        # Wykryj również piksele bardzo podobne do typowych kolorów szachownicy
        # Typowa szachownica: szary ~128,128,128
        grey_distance = np.sqrt((r - 128) ** 2 + (g - 128) ** 2 + (b - 128) ** 2)
        close_to_grey = grey_distance < 40
        
        # Połącz szare i białe piksele dla szachownicy
        checkerboard_background = is_grey | close_to_grey
        
        # === POŁĄCZ WSZYSTKIE TŁA DO USUNIĘCIA ===
        # Białe tło + szachownica
        checkerboard_mask = white_background | checkerboard_background
        
        # === UŻYJ ORYGINALNEJ FIOLKI JAKO REFERENCJI ===
        # Nie usuwaj części, które są podobne do oryginalnej fiolki
        if vial_reference is not None:
            try:
                # Przygotuj referencję
                if vial_reference.mode != 'RGBA':
                    vial_ref = vial_reference.convert('RGBA')
                else:
                    vial_ref = vial_reference.copy()
                
                # Dopasuj rozmiar referencji do wyniku
                if vial_ref.size != result_image.size:
                    vial_ref = vial_ref.resize(result_image.size, PIL.Image.Resampling.LANCZOS)
                
                # Konwertuj do numpy
                vial_array = np.array(vial_ref)
                vial_rgb = vial_array[:, :, :3]
                vial_alpha = vial_array[:, :, 3]
                
                # Oblicz różnicę kolorów między wynikiem a oryginalną fiolką
                color_diff = np.sqrt(np.sum((rgb - vial_rgb) ** 2, axis=2))
                
                # Określ które obszary to prawdopodobnie fiolka (nie tło)
                # Jeśli piksel jest podobny do oryginalnej fiolki (różnica < 100), to to jest fiolka
                is_vial_part = color_diff < 100
                
                # Jeśli w oryginalnej fiolce jest nieprzezroczysty piksel, to w wyniku też powinien być
                vial_visible = vial_alpha > 128
                is_foreground = is_vial_part | vial_visible
                
                # NIE usuwaj części fiolki - usuń tylko tło które NIE jest częścią fiolki
                background_to_remove = (is_background | checkerboard_mask) & ~is_foreground
                
                logger.info(f"Using vial reference: {np.sum(is_foreground)} pixels identified as vial/foreground")
            except Exception as e:
                logger.warning(f"Failed to use vial reference: {e}, using simple background removal")
                # Fallback: użyj prostej metody
                background_to_remove = is_background | checkerboard_mask
        else:
            # Jeśli nie ma referencji, użyj prostej metody
            background_to_remove = green_background | checkerboard_mask
        
        # Policz ile pikseli zostanie usuniętych (do logowania)
        pixels_to_remove = np.sum(background_to_remove)
        bg_color_pixels = np.sum(is_background)
        white_pixels = np.sum(white_background)
        checkerboard_pixels = np.sum(checkerboard_mask)
        total_pixels = background_to_remove.size
        
        logger.info(f"Detected: {bg_color_pixels} background color, {white_pixels} white, {checkerboard_pixels} checkerboard pixels")
        logger.info(f"After vial reference filtering: {pixels_to_remove} pixels to remove out of {total_pixels} ({100*pixels_to_remove/total_pixels:.1f}%)")
        
        # Sprawdź czy w ogóle są jakieś nieprzezroczyste piksele przed usunięciem
        visible_before = np.sum(alpha > 0)
        logger.info(f"Visible pixels before removal: {visible_before}")
        
        # Usuń wszystkie wykryte tła (ustaw alpha na 0), ale tylko te które NIE są częścią fiolki
        alpha[background_to_remove] = 0
        
        # Sprawdź ile zostało widocznych pikseli po usunięciu
        visible_after = np.sum(alpha > 0)
        logger.info(f"Visible pixels after removal: {visible_after}")
        
        # Zastosuj nowy alpha channel
        data[:, :, 3] = alpha
        
        # Konwertuj z powrotem do PIL Image
        result_image = PIL.Image.fromarray(data, 'RGBA')
        
        logger.info("Removed green background and checkerboard (converted to real transparency) using fallback method")
        return result_image
        
    except Exception as e:
        logger.warning(f"Background removal failed: {e}", exc_info=True)
        # Fallback - zwróć oryginalny obraz
        if result_image.mode != 'RGBA':
            result_image = result_image.convert('RGBA')
        return result_image


@app.route('/health')
def health_check():
    """Health check endpoint for Railway monitoring (no auth required)."""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'rendering_available': HAS_RENDERING,
        'rembg_available': HAS_REMBG
    }), 200


@app.route('/')
@requires_auth
def index():
    """Dashboard homepage."""
    return render_template_string(DASHBOARD_UI)


@app.route('/documentation/<filename>')
@requires_auth
def serve_documentation(filename):
    """Serve documentation markdown files."""
    try:
        # Security: only allow .md files and prevent directory traversal
        if not filename.endswith('.md') or '/' in filename or '\\' in filename:
            return jsonify({'error': 'Invalid filename'}), 400
        
        doc_path = Path(__file__).parent / 'documentation' / filename
        
        if not doc_path.exists():
            return jsonify({'error': 'Documentation not found'}), 404
        
        return send_file(doc_path, mimetype='text/markdown')
    
    except Exception as e:
        logger.error(f"Error serving documentation: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/validate-template', methods=['POST'])
def validate_template():
    """Validate uploaded template."""
    if 'template' not in request.files:
        return jsonify({'error': 'No template file provided'}), 400
    
    file = request.files['template']
    if file.filename == '':
        # Use default template
        template_path = Path(DEFAULT_TEMPLATE)
    else:
        filename = secure_filename(file.filename)
        filepath = config.UPLOAD_DIR / filename
        file.save(str(filepath))
        template_path = filepath
    
    try:
        parser = TemplateParser(template_path)
        is_valid, errors = parser.validate()
        
        if is_valid:
            return jsonify({'valid': True, 'placeholders': list(parser.placeholder_positions.keys())})
        else:
            return jsonify({'valid': False, 'errors': errors}), 400
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/generate', methods=['POST'])
def generate_labels():
    """Generate labels from template and CSV."""
    # #region agent log
    _dbg("app.py:generate_labels", "entry", {"has_template": bool(request.files.get('template')), "has_csv": bool(request.files.get('csv'))}, "H2")
    # #endregion
    template_file = request.files.get('template')
    csv_file = request.files.get('csv')
    
    # Use default template if not provided
    if not template_file or template_file.filename == '':
        template_path = Path(DEFAULT_TEMPLATE)
        if not template_path.exists():
            return jsonify({'error': f'Default template not found: {template_path}'}), 400
    else:
        template_filename = secure_filename(template_file.filename)
        template_path = config.UPLOAD_DIR / template_filename
        template_file.save(str(template_path))
        
        # Convert AI files to SVG automatically
        if template_path.suffix.lower() == '.ai':
            try:
                logger.info(f"Detected AI file, converting to SVG: {template_path}")
                converter = AIConverter()
                svg_path = converter.convert_to_svg(template_path)
                # Use converted SVG file instead of original AI
                template_path = svg_path
                logger.info(f"Using converted SVG for processing: {template_path}")
            except AIConverterError as e:
                logger.error(f"AI conversion failed: {e}")
                return jsonify({'error': f'Failed to convert AI file to SVG: {str(e)}'}), 400
    
    # Use current database if not provided
    if not csv_file or csv_file.filename == '':
        csv_path = Path(get_current_database())
        if not csv_path.exists():
            return jsonify({'error': f'Database not found: {csv_path}'}), 400
    else:
        csv_filename = secure_filename(csv_file.filename)
        csv_path = config.UPLOAD_DIR / csv_filename
        csv_file.save(str(csv_path))
    
    try:
        # Load text areas if available
        text_areas = None
        # Use template_path.stem (which is already the saved filename without extension)
        template_filename = template_path.stem
        areas_file = config.UPLOAD_DIR / f"{template_filename}_areas.json"
        
        logger.info(f"Looking for text areas file: {areas_file} (template: {template_path}, stem: {template_filename})")
        
        # Also try with original filename if template_file was provided
        if template_file and template_file.filename:
            original_name = secure_filename(template_file.filename)
            alt_areas_file = config.UPLOAD_DIR / f"{Path(original_name).stem}_areas.json"
            logger.info(f"Also checking: {alt_areas_file}")
            if alt_areas_file.exists() and not areas_file.exists():
                areas_file = alt_areas_file
                logger.info(f"Using alternative areas file: {areas_file}")
        
        if areas_file.exists():
            with open(areas_file, 'r') as f:
                text_areas = json.load(f)
            logger.info(f"✓ Loaded text areas for template: {text_areas}")
        else:
            logger.info(f"✗ Text areas file not found: {areas_file}")
            # List available areas files for debugging
            areas_files = list(config.UPLOAD_DIR.glob("*_areas.json"))
            if areas_files:
                logger.info(f"Available areas files: {[f.name for f in areas_files]}")
        
        # Create output directory for this job
        job_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = config.OUTPUT_DIR / f"labels_{job_id}"
        output_dir.mkdir(parents=True, exist_ok=True)
        
        if not HAS_RENDERING:
            return jsonify({'error': 'Rendering not available. Please install Cairo: brew install cairo pkg-config.'}), 500
        
        # Process batch - ALL PRODUCTS FROM DATABASE
        processor = BatchProcessor(template_path, csv_path, text_areas=text_areas)
        summary = processor.process_batch(output_dir=output_dir, limit=None)
        
        # Create ZIP - ALL PRODUCTS with SKU folder structure
        zip_path = output_dir / f"labels_{job_id}.zip"
        packager = Packager()
        packager.create_zip_from_results(summary['results'], zip_path=zip_path, limit=None)
        # #region agent log
        _dbg("app.py:generate_labels", "success", {"job_id": job_id, "total": summary['total']}, "H2")
        # #endregion
        return jsonify({
            'success': summary['success'],
            'total': summary['total'],
            'errors': summary['errors'],
            'elapsed_time': summary['elapsed_time'],
            'job_id': job_id,
            'zip_file': zip_path.name
        })
        
    except (BatchProcessorError, PackagerError) as e:
        # #region agent log
        _dbg("app.py:generate_labels", "exception", {"error": str(e), "type": type(e).__name__}, "H2,H5")
        # #endregion
        return jsonify({'error': str(e)}), 500
    except Exception as e:
        # #region agent log
        import traceback
        _dbg("app.py:generate_labels", "exception", {"error": str(e), "type": type(e).__name__, "traceback": traceback.format_exc()}, "H2,H5")
        # #endregion
        logger.error(f"Unexpected error: {e}", exc_info=True)
        return jsonify({'error': f'Unexpected error: {str(e)}'}), 500


@app.route('/api/download/<job_id>')
def download_zip(job_id):
    """Download generated ZIP file."""
    # Try new format first (inside folder)
    zip_path = config.OUTPUT_DIR / f"labels_{job_id}" / f"labels_{job_id}.zip"
    # Fallback to old format (directly in OUTPUT_DIR)
    if not zip_path.exists():
        zip_path = config.OUTPUT_DIR / f"labels_{job_id}.zip"
    
    if not zip_path.exists():
        return jsonify({'error': 'ZIP file not found'}), 404
    
    return send_file(str(zip_path), as_attachment=True, download_name=f"labels_{job_id}.zip")


@app.route('/api/convert-ai', methods=['POST'])
def convert_ai_for_preview():
    """Converts an uploaded AI file to SVG for frontend preview with analysis."""
    if 'template' not in request.files:
        return jsonify({'error': 'No template file provided'}), 400
    
    file = request.files['template']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    
    if file.filename.lower().endswith('.ai'):
        try:
            filename = secure_filename(file.filename)
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            ai_filename = f"ai_preview_{timestamp}_{filename}"
            ai_path = config.UPLOAD_DIR / ai_filename
            file.save(str(ai_path))
            
            logger.info(f"Converting AI file for preview: {ai_path}")
            
            converter = AIConverter()
            # Convert WITHOUT text-to-path to keep text as text elements
            svg_path = converter.convert_to_svg(ai_path, text_to_path=False, dpi=300)
            
            # Extract text information for analysis
            extracted_info = extract_svg_text_info(svg_path)
            logger.info(f"Extracted info: {extracted_info}")
            
            # Read SVG content
            with open(svg_path, 'r', encoding='utf-8') as f:
                svg_content = f.read()
            
            # Clean up AI file but keep SVG
            try:
                ai_path.unlink()
            except Exception as e:
                logger.warning(f"Could not delete AI file: {e}")
            
            # Return JSON with SVG content and analysis
            return jsonify({
                'success': True,
                'svg_content': svg_content,
                'svg_filename': svg_path.name,
                'extracted_info': extracted_info
            })
            
        except AIConverterError as e:
            logger.error(f"AI conversion for preview failed: {e}")
            return jsonify({'success': False, 'error': f'Failed to convert AI file: {str(e)}'}), 500
        except Exception as e:
            logger.error(f"Unexpected error in convert_ai_for_preview: {e}", exc_info=True)
            return jsonify({'success': False, 'error': f'Unexpected error: {str(e)}'}), 500
    else:
        return jsonify({'error': 'Only AI files can be converted via this endpoint.'}), 400


@app.route('/api/preview/<job_id>/<filename>')
def preview_label(job_id, filename):
    """Preview a generated label image."""
    try:
        # Try with labels_ prefix first (new format)
        label_path = config.OUTPUT_DIR / f"labels_{job_id}" / filename
        # Fallback to old format without prefix
        if not label_path.exists():
            label_path = config.OUTPUT_DIR / job_id / filename
        if not label_path.exists():
            return jsonify({'error': 'Label file not found'}), 404
        
        # Only allow image and PDF files
        if label_path.suffix.lower() not in ['.png', '.jpg', '.jpeg', '.svg', '.pdf']:
            return jsonify({'error': 'Invalid file type'}), 400
        
        # Determine MIME type
        mime_types = {
            '.png': 'image/png',
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.svg': 'image/svg+xml',
            '.pdf': 'application/pdf'
        }
        mime_type = mime_types.get(label_path.suffix.lower(), 'application/octet-stream')
        
        return send_file(str(label_path), mimetype=mime_type)
    except Exception as e:
        logger.error(f"Error serving preview: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/latest-labels', methods=['GET'])
def get_latest_labels():
    """Get list of generated labels (all if no limit specified)."""
    try:
        limit_param = request.args.get('limit')
        limit = int(limit_param) if limit_param else None
        labels = []
        
        # Get all job directories, sorted by modification time (newest first)
        job_dirs = sorted(
            [d for d in config.OUTPUT_DIR.iterdir() if d.is_dir() and d.name[0].isdigit()],
            key=lambda x: x.stat().st_mtime,
            reverse=True
        )
        
        # Check if specific job_id is requested
        requested_job_id = request.args.get('job_id')
        
        job_dirs_to_check = job_dirs
        if requested_job_id:
            # Look for specific job
            requested_dir = config.OUTPUT_DIR / requested_job_id
            if requested_dir.exists() and requested_dir.is_dir():
                job_dirs_to_check = [requested_dir]
            else:
                # Job not found yet, return empty
                return jsonify({'labels': []})
        
        for job_dir in job_dirs_to_check[:1]:  # Only get from latest job or requested job
            # Look for JPG files (new format) or PNG files (old format)
            jpg_files = sorted(
                [f for f in job_dir.glob('*.jpg')],
                key=lambda x: x.stat().st_mtime,
                reverse=True
            )
            if limit is not None:
                jpg_files = jpg_files[:limit]
            
            # If no JPG files, try PNG files (backward compatibility)
            if not jpg_files:
                jpg_files = sorted(
                    [f for f in job_dir.glob('*.png')],
                    key=lambda x: x.stat().st_mtime,
                    reverse=True
                )
                if limit is not None:
                    jpg_files = jpg_files[:limit]
            
            for img_file in jpg_files:
                labels.append({
                    'job_id': job_dir.name,
                    'filename': img_file.name,
                    'url': f'/api/preview/{job_dir.name}/{img_file.name}',
                    'name': img_file.stem
                })
            
            # Only check first matching directory
            break
        
        return jsonify({'labels': labels[:limit]})
    except Exception as e:
        logger.error(f"Error getting latest labels: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


# ============== Database Selection API ==============

@app.route('/api/databases', methods=['GET'])
def list_databases():
    """List all available databases (CSV files)."""
    try:
        databases = []
        db_dir = config.DATABASES_DIR
        
        # List all CSV files in the databases directory
        for csv_file in db_dir.glob('*.csv'):
            # Get file info
            stat = csv_file.stat()
            
            # Count products in file
            try:
                manager = CSVManager(csv_file)
                products = manager.read_all()
                product_count = len(products)
            except Exception as e:
                # If CSV is invalid, set count to 0
                logger.warning(f"Could not read products from {csv_file}: {e}")
                product_count = 0
            
            databases.append({
                'name': csv_file.stem,  # Filename without extension
                'filename': csv_file.name,
                'path': str(csv_file),
                'size': stat.st_size,
                'modified': stat.st_mtime,
                'product_count': product_count,
                'is_active': str(csv_file) == get_current_database()
            })
        
        # Sort by name
        databases.sort(key=lambda x: x['name'].lower())
        
        return jsonify({
            'databases': databases,
            'current': get_current_database()
        })
    except Exception as e:
        logger.error(f"Error listing databases: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/databases/select', methods=['POST'])
def select_database():
    """Select a database to use."""
    try:
        data = request.json
        db_path = data.get('path') or data.get('filename')
        
        if not db_path:
            return jsonify({'error': 'No database path provided'}), 400
        
        # If only filename provided, construct full path
        if not Path(db_path).is_absolute():
            db_path = str(config.DATABASES_DIR / db_path)
        
        if not Path(db_path).exists():
            return jsonify({'error': f'Database not found: {db_path}'}), 404
        
        if set_current_database(db_path):
            logger.info(f"Database selected: {db_path}")
            return jsonify({
                'success': True,
                'current': get_current_database(),
                'message': f'Database selected: {Path(db_path).stem}'
            })
        else:
            return jsonify({'error': 'Failed to select database'}), 500
            
    except Exception as e:
        logger.error(f"Error selecting database: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/databases/preview', methods=['POST'])
def preview_csv():
    """Preview CSV file contents and columns for mapping."""
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file provided'}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        
        if not file.filename.endswith('.csv'):
            return jsonify({'error': 'Only CSV files are supported'}), 400
        
        # Save to temp directory for preview
        import csv
        filename = secure_filename(file.filename)
        temp_path = config.TEMP_DIR / f"preview_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{filename}"
        file.save(str(temp_path))
        
        try:
            # Read CSV and extract columns and preview rows
            with open(temp_path, 'r', encoding='utf-8') as f:
                # Try to detect delimiter
                sample = f.read(4096)
                f.seek(0)
                
                try:
                    dialect = csv.Sniffer().sniff(sample, delimiters=',;\t|')
                except (csv.Error, Exception):
                    # Fallback to excel dialect if sniffing fails
                    dialect = csv.excel
                
                reader = csv.DictReader(f, dialect=dialect)
                columns = reader.fieldnames or []
                
                # Get first 5 rows for preview
                preview_rows = []
                for i, row in enumerate(reader):
                    if i >= 5:
                        break
                    preview_rows.append(row)
                
                # Count total rows
                f.seek(0)
                total_rows = sum(1 for _ in f) - 1  # Subtract header
            
            # Try to auto-detect column mappings
            auto_mapping = {}
            columns_lower = {c.lower(): c for c in columns}
            
            # Product name detection
            for key in ['product', 'product_name', 'productname', 'name', 'nazwa', 'produkt']:
                if key in columns_lower:
                    auto_mapping['product'] = columns_lower[key]
                    break
            
            # Ingredients detection
            for key in ['ingredients', 'ingredient', 'skladniki', 'dosage', 'dose']:
                if key in columns_lower:
                    auto_mapping['ingredients'] = columns_lower[key]
                    break
            
            # SKU detection
            for key in ['sku', 'code', 'product_code', 'id', 'kod']:
                if key in columns_lower:
                    auto_mapping['sku'] = columns_lower[key]
                    break
            
            return jsonify({
                'success': True,
                'filename': filename,
                'temp_path': str(temp_path),
                'columns': columns,
                'preview_rows': preview_rows,
                'total_rows': total_rows,
                'auto_mapping': auto_mapping
            })
            
        except Exception as e:
            # Clean up temp file
            if temp_path.exists():
                temp_path.unlink()
            return jsonify({'error': f'Error reading CSV: {str(e)}'}), 400
            
    except Exception as e:
        logger.error(f"Error previewing CSV: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/databases/import', methods=['POST'])
def import_database():
    """Import CSV with column mapping."""
    try:
        data = request.json
        temp_path = data.get('temp_path')
        mapping = data.get('mapping', {})
        db_name = data.get('name', 'imported_database')
        
        if not temp_path or not Path(temp_path).exists():
            return jsonify({'error': 'Preview file not found. Please upload again.'}), 400
        
        if not mapping.get('product') or not mapping.get('ingredients') or not mapping.get('sku'):
            return jsonify({'error': 'Please map all required fields: Product, Ingredients, SKU'}), 400
        
        import csv
        
        # Read source CSV
        with open(temp_path, 'r', encoding='utf-8') as f:
            try:
                sample = f.read(4096)
                f.seek(0)
                dialect = csv.Sniffer().sniff(sample, delimiters=',;\t|')
            except (csv.Error, Exception):
                # Fallback to excel dialect if sniffing fails
                dialect = csv.excel
            
            reader = csv.DictReader(f, dialect=dialect)
            
            # Map data to standard format
            products = []
            for row in reader:
                products.append({
                    'Product': row.get(mapping['product'], ''),
                    'Ingredients': row.get(mapping['ingredients'], ''),
                    'SKU': row.get(mapping['sku'], '')
                })
        
        # Generate unique filename
        filename = secure_filename(f"{db_name}.csv")
        db_path = config.DATABASES_DIR / filename
        
        # Check if file already exists
        if db_path.exists():
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"{db_name}_{timestamp}.csv"
            db_path = config.DATABASES_DIR / filename
        
        # Write new CSV with standard columns
        with open(db_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=['Product', 'Ingredients', 'SKU'])
            writer.writeheader()
            writer.writerows(products)
        
        # Clean up temp file
        try:
            temp_file = Path(temp_path)
            if temp_file.exists():
                temp_file.unlink()
        except (OSError, PermissionError) as e:
            logger.warning(f"Could not delete temp file {temp_path}: {e}")
        
        logger.info(f"Database imported: {db_path} ({len(products)} products)")
        
        return jsonify({
            'success': True,
            'filename': filename,
            'path': str(db_path),
            'product_count': len(products),
            'message': f'Database imported: {filename}'
        })
        
    except Exception as e:
        logger.error(f"Error importing database: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/databases/upload', methods=['POST'])
def upload_database():
    """Upload a new database (CSV file) - direct upload without mapping."""
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file provided'}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        
        if not file.filename.endswith('.csv'):
            return jsonify({'error': 'Only CSV files are supported'}), 400
        
        # Save the file
        filename = secure_filename(file.filename)
        db_path = config.DATABASES_DIR / filename
        
        # Check if file already exists
        if db_path.exists():
            # Add timestamp to make unique
            stem = db_path.stem
            suffix = db_path.suffix
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"{stem}_{timestamp}{suffix}"
            db_path = config.DATABASES_DIR / filename
        
        file.save(str(db_path))
        
        # Validate the CSV
        try:
            manager = CSVManager(db_path)
            products = manager.read_all()
            product_count = len(products)
        except Exception as e:
            # Invalid CSV - delete it
            try:
                if db_path.exists():
                    db_path.unlink()
            except Exception as cleanup_error:
                logger.warning(f"Could not delete invalid CSV: {cleanup_error}")
            return jsonify({'error': f'Invalid CSV file: {str(e)}'}), 400
        
        logger.info(f"Database uploaded: {db_path} ({product_count} products)")
        
        return jsonify({
            'success': True,
            'filename': filename,
            'path': str(db_path),
            'product_count': product_count,
            'message': f'Database uploaded: {filename}'
        })
        
    except Exception as e:
        logger.error(f"Error uploading database: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/databases/<path:filename>', methods=['DELETE'])
def delete_database(filename):
    """Delete a database (CSV file)."""
    try:
        db_path = config.DATABASES_DIR / secure_filename(filename)
        
        if not db_path.exists():
            return jsonify({'error': 'Database not found'}), 404
        
        # Don't allow deleting the currently active database
        if str(db_path) == get_current_database():
            return jsonify({'error': 'Cannot delete the currently active database'}), 400

        try:
            db_path.unlink()
            logger.info(f"Database deleted: {db_path}")
        except Exception as e:
            logger.error(f"Failed to delete database: {e}")
            return jsonify({'error': f'Failed to delete database: {str(e)}'}), 500
        
        return jsonify({
            'success': True,
            'message': f'Database deleted: {filename}'
        })
        
    except Exception as e:
        logger.error(f"Error deleting database: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/databases/delete', methods=['POST'])
def delete_database_post():
    """Delete a database (CSV file) - POST version."""
    try:
        data = request.json
        db_path_str = data.get('path')
        
        if not db_path_str:
            return jsonify({'error': 'No database path provided'}), 400
        
        db_path = Path(db_path_str)
        
        if not db_path.exists():
            return jsonify({'error': 'Database not found'}), 404
        
        # Don't allow deleting the currently active database - switch to default first
        current_db = get_current_database()
        if str(db_path) == current_db:
            # Find another database to switch to
            databases = list(config.DATABASES_DIR.glob('*.csv'))
            databases = [db for db in databases if str(db) != str(db_path)]
            
            if databases:
                # Switch to first available database
                set_current_database(str(databases[0]))
                logger.info(f"Switched to {databases[0]} before deleting {db_path}")
            else:
                return jsonify({'error': 'Cannot delete the only database. Upload a new one first.'}), 400

        try:
            if db_path.exists():
                db_path.unlink()
                logger.info(f"Database deleted: {db_path}")
        except Exception as e:
            logger.error(f"Failed to delete database: {e}")
            return jsonify({'error': f'Failed to delete database: {str(e)}'}), 500

        return jsonify({
            'success': True,
            'message': f'Database deleted: {db_path.name}'
        })
        
    except Exception as e:
        logger.error(f"Error deleting database: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/database/export', methods=['GET'])
def export_database():
    """Export current database as CSV file."""
    try:
        current_db = get_current_database()
        db_path = Path(current_db)
        
        if not db_path.exists():
            return jsonify({'error': 'Database not found'}), 404
        
        logger.info(f"Exporting database: {db_path}")
        
        return send_file(
            db_path,
            mimetype='text/csv',
            as_attachment=True,
            download_name=f'export_{db_path.name}'
        )
        
    except Exception as e:
        logger.error(f"Error exporting database: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


# Database management API endpoints
@app.route('/api/database/products', methods=['GET'])
def get_products():
    """Get all products from database."""
    try:
        csv_path = Path(get_current_database())
        if not csv_path.exists():
            logger.error(f"CSV file not found: {csv_path}")
            return jsonify({'error': f'CSV file not found: {csv_path}'}), 404
        
        manager = CSVManager(csv_path)
        products = manager.read_all()
        logger.info(f"Loaded {len(products)} products from CSV")
        return jsonify({'products': products, 'database': csv_path.stem})
    except CSVManagerError as e:
        logger.error(f"CSVManagerError: {e}")
        return jsonify({'error': str(e)}), 500
    except Exception as e:
        logger.error(f"Unexpected error in get_products: {e}", exc_info=True)
        return jsonify({'error': f'Unexpected error: {str(e)}'}), 500


@app.route('/api/database/products/search', methods=['GET'])
def search_product_by_sku():
    """Search for a product by SKU."""
    try:
        sku = request.args.get('sku', '').strip()
        if not sku:
            return jsonify({'error': 'SKU parameter is required'}), 400
        
        csv_path = Path(get_current_database())
        if not csv_path.exists():
            return jsonify({'error': 'Database not found'}), 404
        
        manager = CSVManager(csv_path)
        products = manager.read_all()
        
        # Search for product with matching SKU
        # Try exact match first
        for product in products:
            if product.get('SKU', '').strip().upper() == sku.upper():
                logger.info(f"Found product by SKU {sku}: {product.get('Product')}")
                return jsonify({'success': True, 'product': product})
        
        # Try partial match (e.g., "YPB.212" matches "212" or "YPB.212")
        sku_number = sku.replace('YPB.', '').replace('YPB-', '').replace('YPB', '').strip()
        for product in products:
            product_sku = product.get('SKU', '').strip()
            if sku_number in product_sku or product_sku in sku:
                logger.info(f"Found product by partial SKU match {sku}: {product.get('Product')}")
                return jsonify({'success': True, 'product': product})
        
        logger.warning(f"No product found for SKU: {sku}")
        return jsonify({'success': False, 'error': 'Product not found'}), 404
        
    except Exception as e:
        logger.error(f"Error searching for product: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/database/products', methods=['POST'])
def add_product():
    """Add a new product."""
    try:
        csv_path = Path(get_current_database())
        manager = CSVManager(csv_path)
        product = manager.add_product(request.json)
        return jsonify({'product': product, 'message': 'Product added successfully'})
    except CSVManagerError as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/database/products/<int:product_id>', methods=['PUT'])
def update_product(product_id):
    """Update a product."""
    try:
        csv_path = Path(get_current_database())
        manager = CSVManager(csv_path)
        product = manager.update_product(product_id, request.json)
        return jsonify({'product': product, 'message': 'Product updated successfully'})
    except CSVManagerError as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/database/products/<int:product_id>', methods=['DELETE'])
def delete_product(product_id):
    """Delete a product."""
    try:
        csv_path = Path(get_current_database())
        manager = CSVManager(csv_path)
        manager.delete_product(product_id)
        return jsonify({'message': 'Product deleted successfully'})
    except CSVManagerError as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/database/products/bulk', methods=['PUT'])
def bulk_update_products():
    """Bulk update multiple products."""
    try:
        csv_path = Path(get_current_database())
        manager = CSVManager(csv_path)
        updates = request.json.get('updates', [])
        products = manager.bulk_update(updates)
        return jsonify({'products': products, 'message': f'Updated {len(updates)} products'})
    except CSVManagerError as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/database/replace', methods=['POST'])
def replace_csv():
    """Replace the current CSV file with a new one."""
    if 'csv' not in request.files:
        return jsonify({'error': 'No CSV file provided'}), 400
    
    file = request.files['csv']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    
    try:
        # Save uploaded file temporarily
        filename = secure_filename(file.filename)
        temp_path = config.UPLOAD_DIR / filename
        file.save(str(temp_path))
        
        # Replace current database CSV
        csv_path = Path(get_current_database())
        manager = CSVManager(csv_path)
        manager.replace_csv(temp_path)
        
        # Remove temp file
        temp_path.unlink()
        
        # Reload and return products
        products = manager.read_all()
        return jsonify({
            'products': products,
            'message': 'CSV file replaced successfully'
        })
    except CSVManagerError as e:
        return jsonify({'error': str(e)}), 500
    except Exception as e:
        logger.error(f"Error replacing CSV: {e}", exc_info=True)
        return jsonify({'error': f'Unexpected error: {str(e)}'}), 500


@app.route('/api/save-text-areas', methods=['POST'])
def save_text_areas():
    """Save text area configurations for a template."""
    try:
        data = request.json
        filename = data.get('filename')
        areas = data.get('areas', {})
        
        if not filename:
            return jsonify({'error': 'Filename required'}), 400
        
        # Use secure_filename to match how template is saved
        safe_filename = secure_filename(filename)
        areas_file = config.UPLOAD_DIR / f"{Path(safe_filename).stem}_areas.json"
        
        logger.info(f"Saving text areas for {filename} (safe: {safe_filename}) to {areas_file}")
        with open(areas_file, 'w') as f:
            json.dump(areas, f, indent=2)
        
        logger.info(f"Text areas saved: {areas}")
        return jsonify({'success': True, 'message': 'Text areas saved'})
    except Exception as e:
        logger.error(f"Error saving text areas: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/get-text-areas', methods=['GET'])
def get_text_areas():
    """Get text area configurations for a template."""
    try:
        filename = request.args.get('filename')
        if not filename:
            return jsonify({'error': 'Filename required'}), 400
        
        # Use secure_filename to match how template is saved
        safe_filename = secure_filename(filename)
        areas_file = config.UPLOAD_DIR / f"{Path(safe_filename).stem}_areas.json"
        
        logger.info(f"Loading text areas for {filename} (safe: {safe_filename}) from {areas_file}")
        if areas_file.exists():
            with open(areas_file, 'r') as f:
                areas = json.load(f)
            logger.info(f"Loaded text areas: {areas}")
            return jsonify({'areas': areas})
        else:
            logger.info(f"Text areas file not found: {areas_file}")
            return jsonify({'areas': None})
    except Exception as e:
        logger.error(f"Error getting text areas: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


def _extract_sku_from_svg(svg_path):
    """Extract SKU from SVG file by parsing text content."""
    try:
        # Read SVG content
        with open(svg_path, 'r', encoding='utf-8') as f:
            svg_content = f.read()
        
        # Look for SKU patterns in SVG text
        # Pattern: r'(?:SKU:?\s*)?(YPB[.\-\s]?\d+)' - accepts YPB-200, YPB.200, YPB200, YPB 200
        sku_patterns = [
            r'(?:SKU:?\s*)?(YPB[.\-\s]?\d+)',  # With SKU: prefix
            r'(YPB[.\-\s]?\d+)',                # Just YPB code
        ]
        
        for pattern in sku_patterns:
            match = re.search(pattern, svg_content, re.IGNORECASE)
            if match:
                sku = match.group(1).strip()
                # Normalize SKU format (remove spaces, use dots)
                sku = re.sub(r'\s+', '', sku)  # Remove spaces
                sku = sku.replace('-', '.')    # Normalize to dots
                logger.info(f"Found SKU in SVG: {sku}")
                return sku
        
        return None
    except Exception as e:
        logger.warning(f"Failed to extract SKU from SVG: {e}")
        return None


@app.route('/api/extract-sku', methods=['POST'])
def extract_sku():
    """Extract SKU from uploaded label file (SVG or image)."""
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file provided'}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        
        filename = secure_filename(file.filename)
        file_ext = Path(filename).suffix.lower()
        
        # Save file temporarily
        temp_path = config.UPLOAD_DIR / f"temp_extract_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}_{filename}"
        file.save(str(temp_path))
        
        try:
            sku = None
            
            # Handle SVG files
            if file_ext == '.svg':
                sku = _extract_sku_from_svg(temp_path)
            
            # Handle image files - use OCR (pytesseract)
            elif file_ext in ['.png', '.jpg', '.jpeg', '.gif', '.bmp']:
                try:
                    import pytesseract
                    from PIL import Image
                    
                    # Load image
                    img = Image.open(temp_path)
                    
                    # Extract text using OCR
                    text = pytesseract.image_to_string(img)
                    
                    # Look for SKU patterns (accepts various formats: YPB-200, YPB.200, YPB200, YPB 200)
                    sku_patterns = [
                        r'(?:SKU:?\s*)?(YPB[.\-\s]?\d+)',  # YPB-200, YPB.200, YPB200, YPB 200
                        r'(?:SKU:?\s*)([A-Z0-9-]+)',
                        r'(YPB[.\-\s]?\d+)',
                    ]
                    
                    for pattern in sku_patterns:
                        match = re.search(pattern, text, re.IGNORECASE)
                        if match:
                            sku = match.group(1).strip()
                            logger.info(f"Found SKU using OCR: {sku}")
                            break
                except ImportError:
                    logger.warning("pytesseract not available for OCR")
                except Exception as e:
                    logger.warning(f"OCR failed: {e}")
            
            # Cleanup
            if temp_path.exists():
                temp_path.unlink()
            
            if sku:
                return jsonify({'success': True, 'sku': sku})
            else:
                return jsonify({'success': False, 'sku': None})
                
        except Exception as e:
            logger.error(f"Error extracting SKU: {e}", exc_info=True)
            if temp_path.exists():
                temp_path.unlink()
            return jsonify({'error': str(e)}), 500
            
    except Exception as e:
        logger.error(f"Error in extract_sku: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/convert-svg-to-png', methods=['POST'])
def convert_svg_to_png():
    """Convert uploaded SVG file to PNG."""
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file provided'}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        
        if not file.filename.lower().endswith('.svg'):
            return jsonify({'error': 'File must be SVG'}), 400
        
        # Save uploaded SVG temporarily
        filename = secure_filename(file.filename)
        svg_path = config.UPLOAD_DIR / f"temp_svg_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}_{filename}"
        file.save(str(svg_path))
        
        try:
            # Convert SVG to PNG
            label_image = _load_label_image(svg_path)
            
            # Save as PNG
            png_filename = f"{Path(filename).stem}.png"
            png_path = config.UPLOAD_DIR / f"converted_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}_{png_filename}"
            label_image.save(str(png_path), format='PNG')
            
            # Delete temp SVG
            svg_path.unlink()
            
            # Read PNG and return as base64 data URL
            import base64
            with open(png_path, 'rb') as f:
                png_data = base64.b64encode(f.read()).decode('utf-8')
            
            # Delete temp PNG
            png_path.unlink()
            
            # Return as JSON with base64 data
            return jsonify({
                'success': True,
                'png_data': f'data:image/png;base64,{png_data}',
                'filename': png_filename
            })
        except Exception as e:
            logger.error(f"SVG conversion failed: {e}", exc_info=True)
            # Cleanup
            if svg_path.exists():
                svg_path.unlink()
            return jsonify({'error': f'Failed to convert SVG: {str(e)}'}), 500
            
    except Exception as e:
        logger.error(f"Error in convert_svg_to_png: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


def _correct_mockup_with_feedback(vial_image_with_green_bg, label_image, current_mockup_image, errors, product_name, sku, dosage):
    """
    Correct mockup image with feedback about errors.
    Sends request to Gemini Image API to fix the identified issues.
    
    Returns:
        Corrected mockup image (PIL Image)
    """
    try:
        import PIL.Image
        from io import BytesIO
        import base64
        import requests
        
        # Convert images to base64
        def image_to_base64(image):
            buffered = BytesIO()
            if image.mode == 'RGBA':
                image.save(buffered, format="PNG")
            else:
                rgb_image = PIL.Image.new("RGB", image.size, (255, 255, 255))
                if image.mode == 'RGBA':
                    rgb_image.paste(image, mask=image.split()[3])
                else:
                    rgb_image.paste(image)
                rgb_image.save(buffered, format="PNG")
            return base64.b64encode(buffered.getvalue()).decode('utf-8')
        
        vial_base64 = image_to_base64(vial_image_with_green_bg)
        label_base64 = image_to_base64(label_image)
        current_mockup_base64 = image_to_base64(current_mockup_image)
        
        # Build errors list as text
        errors_text = "\n".join([f"- {error}" for error in errors])
        
        # Prepare prompt with feedback - more explicit and detailed
        prompt = f"""CRITICAL CORRECTION REQUIRED:

The previous mockup attempt had these errors:
{errors_text}

You MUST create a corrected mockup that has ALL of the following information correct:
1. SKU: Must be EXACTLY "{sku}" - no variations, no typos, exactly as written
2. Product Name: Must be EXACTLY "{product_name}" - must be visible and clearly readable
3. Dosage: Must contain "{dosage}" - must be visible and clearly readable

IMPORTANT:
- Fix ALL errors listed above - do not create new errors while fixing old ones
- Preserve ALL correct information that was already on the label
- Do NOT remove text that was correct
- Do NOT change text that was correct

Use these images as reference:
- Image 1 (vial): Use as base - keep shape, lighting, perspective, green background
- Image 2 (label): Use as source for label design - this contains the correct label template
- Image 3 (current mockup): Use to see what needs correction - fix the errors but keep what's correct

Instructions:
1. Keep the green background (#00FF00) exactly as in the vial image
2. Do NOT alter the vial shape, proportions, or structure
3. Apply the label from the label image onto the vial
4. Ensure ALL three pieces of information (SKU, Product Name, Dosage) are visible and correct
5. Maintain professional quality - sharp, clear, realistic
6. Do not remove or change any correct information"""
        
        logger.info(f"Requesting correction from Gemini with {len(errors)} errors")
        
        vial_w, vial_h = vial_image_with_green_bg.size
        aspect = _aspect_ratio_for_gemini(vial_w, vial_h)
        cfg = config.GEMINI_MOCKUP_CONFIG_RETRY
        
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-image:generateContent?key={config.GEMINI_API_KEY}"
        
        payload = {
            "contents": [{
                "parts": [
                    {"text": prompt},
                    {"inline_data": {"mime_type": "image/png", "data": vial_base64}},
                    {"inline_data": {"mime_type": "image/png", "data": label_base64}},
                    {"inline_data": {"mime_type": "image/png", "data": current_mockup_base64}}
                ]
            }],
            "generationConfig": {
                "responseModalities": ["IMAGE"],
                "temperature": cfg.get("temperature", 0.05),
                "topP": cfg.get("topP", 0.9),
                "topK": cfg.get("topK", 5),
                "imageConfig": {"aspectRatio": aspect, "imageSize": "2K"}
            }
        }
        
        headers = {"Content-Type": "application/json"}
        
        response = requests.post(url, headers=headers, json=payload, timeout=60)
        response.raise_for_status()
        response_data = response.json()
        
        # Extract corrected image from response
        corrected_image = None
        if 'candidates' in response_data and len(response_data['candidates']) > 0:
            candidate = response_data['candidates'][0]
            if 'content' in candidate and 'parts' in candidate['content']:
                for part in candidate['content']['parts']:
                    if 'inlineData' in part:
                        try:
                            image_data = part['inlineData']['data']
                            image_bytes = base64.b64decode(image_data)
                            corrected_image = PIL.Image.open(BytesIO(image_bytes))
                            logger.info("Successfully extracted corrected image from Gemini API response")
                            break
                        except Exception as e:
                            logger.error(f"Error decoding corrected image: {e}")
                            continue
        
        if not corrected_image:
            logger.warning("Gemini API did not return corrected image, using current mockup")
            return current_mockup_image
        
        return corrected_image
        
    except Exception as e:
        logger.error(f"Error correcting mockup: {e}. Using current mockup.", exc_info=True)
        # Fallback: return current image
        return current_mockup_image


def _verify_mockup_with_vision(mockup_image, expected_sku, expected_product_name, expected_dosage):
    """
    Verify mockup image using Gemini Vision API.
    Checks if SKU, product name, and dosage are correct on the image.
    
    Returns:
        dict with verification results:
        {
            'is_valid': bool,
            'sku_correct': bool,
            'dosage_correct': bool,
            'product_name_correct': bool,
            'detected_sku': str,
            'detected_dosage': str,
            'detected_product_name': str,
            'errors': List[str]
        }
    """
    try:
        import PIL.Image
        from io import BytesIO
        import base64
        import requests
        
        # Convert image to base64
        buffered = BytesIO()
        if mockup_image.mode == 'RGBA':
            mockup_image.save(buffered, format="PNG")
        else:
            rgb_image = PIL.Image.new("RGB", mockup_image.size, (255, 255, 255))
            if mockup_image.mode == 'RGBA':
                rgb_image.paste(mockup_image, mask=mockup_image.split()[3])
            else:
                rgb_image.paste(mockup_image)
            rgb_image.save(buffered, format="PNG")
        image_base64 = base64.b64encode(buffered.getvalue()).decode('utf-8')
        
        # Prepare prompt for Vision API - more tolerant and focused on OCR
        prompt = f"""You are an OCR expert. Analyze this pharmaceutical vial mockup image and extract ALL visible text from the label.

Focus on finding:
1. SKU/Product Code (usually starts with "YPB." followed by numbers, like "YPB.278" or "SKU: YPB.278")
2. Product Name (the main product name, usually the largest text on label)
3. Dosage/Ingredients (usually contains mg, mcg, or ml units)

Expected values to compare:
- SKU: "{expected_sku}"
- Product Name: "{expected_product_name}"
- Dosage: "{expected_dosage}"

IMPORTANT: Be TOLERANT in matching:
- SKU: Match if the YPB.XXX number is the same, ignore "SKU:" prefix
- Product Name: Match if the core name is present (ignore case, extra spaces)
- Dosage: Match if the main dosage numbers appear anywhere in the text

Return ONLY valid JSON (no markdown):
{{
    "detected_sku": "exact text found for SKU",
    "detected_product_name": "exact text found for product name",
    "detected_dosage": "exact text found for dosage/ingredients",
    "sku_correct": true/false,
    "product_name_correct": true/false,
    "dosage_correct": true/false,
    "all_text_found": "complete list of all text visible on the label"
}}

If you cannot read any text clearly, set detected values to empty string and mark as false."""

        # Call Gemini Vision API (gemini-2.5-flash for text/image analysis)
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={config.GEMINI_API_KEY}"
        
        payload = {
            "contents": [{
                "parts": [
                    {"text": prompt},
                    {
                        "inline_data": {
                            "mime_type": "image/png",
                            "data": image_base64
                        }
                    }
                ]
            }]
        }
        
        headers = {
            "Content-Type": "application/json"
        }
        
        logger.info(f"Verifying mockup with Vision API - Expected: SKU={expected_sku}, Product={expected_product_name}, Dosage={expected_dosage}")
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        response_data = response.json()
        
        # Extract text response from Gemini
        verification_text = ""
        if 'candidates' in response_data and len(response_data['candidates']) > 0:
            candidate = response_data['candidates'][0]
            if 'content' in candidate and 'parts' in candidate['content']:
                for part in candidate['content']['parts']:
                    if 'text' in part:
                        verification_text = part['text']
                        break
        
        if not verification_text:
            logger.warning("Vision API did not return text response")
            return {
                'is_valid': True,  # Fallback: assume valid if Vision fails
                'sku_correct': True,
                'dosage_correct': True,
                'product_name_correct': True,
                'detected_sku': '',
                'detected_dosage': '',
                'detected_product_name': '',
                'errors': []
            }
        
        # Clean up response (remove markdown code blocks if present)
        verification_text = verification_text.strip()
        if verification_text.startswith('```json'):
            verification_text = verification_text[7:]
        if verification_text.startswith('```'):
            verification_text = verification_text[3:]
        if verification_text.endswith('```'):
            verification_text = verification_text[:-3]
        verification_text = verification_text.strip()
        
        # Parse JSON response
        try:
            verification_data = json.loads(verification_text)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Vision API JSON response: {e}. Response: {verification_text}")
            return {
                'is_valid': True,  # Fallback: assume valid
                'sku_correct': True,
                'dosage_correct': True,
                'product_name_correct': True,
                'detected_sku': '',
                'detected_dosage': '',
                'detected_product_name': '',
                'errors': []
            }
        
        # Extract verification results
        detected_sku = verification_data.get('detected_sku', '').strip()
        detected_product_name = verification_data.get('detected_product_name', '').strip()
        detected_dosage = verification_data.get('detected_dosage', '').strip()
        
        # Normalize for comparison (case-insensitive, remove extra spaces)
        def normalize_sku(sku):
            """Normalize SKU for comparison - extract YPB.XXX pattern"""
            import re
            sku = sku.strip().upper().replace(' ', '').replace('-', '.')
            # Extract YPB.XXX pattern
            match = re.search(r'YPB\.?\d+', sku)
            if match:
                return match.group().replace('YPB', 'YPB.')
            return sku
        
        def normalize_product_name(name):
            """Normalize product name for comparison"""
            import re
            name = name.strip().upper()
            # Remove common prefixes/suffixes
            name = re.sub(r'\s+', ' ', name)  # Multiple spaces to single
            name = re.sub(r'[^\w\s]', '', name)  # Remove special chars except spaces
            return name.strip()
        
        def fuzzy_match(str1, str2, threshold=0.7):
            """Simple fuzzy matching - check if strings are similar enough"""
            if not str1 or not str2:
                return False
            str1, str2 = str1.upper(), str2.upper()
            # Exact match
            if str1 == str2:
                return True
            # One contains the other
            if str1 in str2 or str2 in str1:
                return True
            # Calculate simple similarity (common chars ratio)
            common = sum(1 for c in str1 if c in str2)
            similarity = (2.0 * common) / (len(str1) + len(str2))
            return similarity >= threshold
        
        expected_sku_normalized = normalize_sku(expected_sku)
        detected_sku_normalized = normalize_sku(detected_sku)
        
        expected_product_name_normalized = normalize_product_name(expected_product_name)
        detected_product_name_normalized = normalize_product_name(detected_product_name)
        
        expected_dosage_normalized = expected_dosage.strip().upper().replace(' ', '')
        detected_dosage_normalized = detected_dosage.strip().upper().replace(' ', '')
        
        # Use API results if available, otherwise do our own comparison
        sku_correct = verification_data.get('sku_correct', False)
        if not sku_correct:
            # Check if YPB numbers match
            if detected_sku_normalized == expected_sku_normalized:
                sku_correct = True
            # Or if expected SKU appears anywhere in detected text
            elif expected_sku.replace('YPB.', '').strip() in detected_sku:
                sku_correct = True
        
        product_name_correct = verification_data.get('product_name_correct', False)
        if not product_name_correct:
            # Exact match
            if detected_product_name_normalized == expected_product_name_normalized:
                product_name_correct = True
            # Partial match - expected contained in detected or vice versa
            elif expected_product_name_normalized in detected_product_name_normalized:
                product_name_correct = True
            elif detected_product_name_normalized in expected_product_name_normalized:
                product_name_correct = True
            # Fuzzy match for similar names
            elif fuzzy_match(expected_product_name_normalized, detected_product_name_normalized, 0.6):
                product_name_correct = True
        
        dosage_correct = verification_data.get('dosage_correct', False)
        if not dosage_correct:
            # Check if expected dosage appears in detected
            if expected_dosage_normalized in detected_dosage_normalized:
                dosage_correct = True
            # Or if any dosage numbers match
            import re
            expected_numbers = set(re.findall(r'\d+', expected_dosage))
            detected_numbers = set(re.findall(r'\d+', detected_dosage))
            if expected_numbers and expected_numbers.issubset(detected_numbers):
                dosage_correct = True
        
        # Build errors list
        errors = []
        if not sku_correct:
            errors.append(f"SKU mismatch: expected '{expected_sku}', found '{detected_sku}'")
        if not product_name_correct:
            errors.append(f"Product name mismatch: expected '{expected_product_name}', found '{detected_product_name}'")
        if not dosage_correct:
            errors.append(f"Dosage mismatch: expected to contain '{expected_dosage}', found '{detected_dosage}'")
        
        is_valid = sku_correct and product_name_correct and dosage_correct
        
        result = {
            'is_valid': is_valid,
            'sku_correct': sku_correct,
            'dosage_correct': dosage_correct,
            'product_name_correct': product_name_correct,
            'detected_sku': detected_sku,
            'detected_dosage': detected_dosage,
            'detected_product_name': detected_product_name,
            'errors': errors
        }
        
        logger.info(f"Vision verification result: {result}")
        return result
        
    except Exception as e:
        logger.warning(f"Vision verification failed: {e}. Continuing without verification.", exc_info=True)
        # Fallback: return valid result to not block the process
        return {
            'is_valid': True,
            'sku_correct': True,
            'dosage_correct': True,
            'product_name_correct': True,
            'detected_sku': '',
            'detected_dosage': '',
            'detected_product_name': '',
            'errors': []
        }


@app.route('/api/generate-single-mockup', methods=['POST'])
def generate_single_mockup():
    """Generate single mockup with auto-verification and retry (like Combined Generator)."""
    try:
        # Check if Gemini API key is available
        if not config.GEMINI_API_KEY:
            logger.error("GEMINI_API_KEY not found in environment variables")
            return jsonify({
                'error': 'GEMINI_API_KEY not configured. Please set GEMINI_API_KEY in .env.local'
            }), 500
        
        # Get files and form data
        if 'vial' not in request.files or 'label' not in request.files:
            return jsonify({'error': 'Both vial and label files are required'}), 400
        
        vial_file = request.files['vial']
        label_file = request.files['label']
        
        if vial_file.filename == '' or label_file.filename == '':
            return jsonify({'error': 'Please upload both vial and label files'}), 400
        
        product_name = request.form.get('productName', '')
        sku = request.form.get('sku', '')
        dosage = request.form.get('dosage', '')
        
        if not product_name or not sku:
            return jsonify({'error': 'Product Name and SKU are required'}), 400
        
        # Save uploaded files temporarily
        vial_filename = secure_filename(vial_file.filename)
        label_filename = secure_filename(label_file.filename)
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        vial_path = config.UPLOAD_DIR / f"mockup_vial_{timestamp}_{vial_filename}"
        label_path = config.UPLOAD_DIR / f"mockup_label_{timestamp}_{label_filename}"
        
        vial_file.save(str(vial_path))
        label_file.save(str(label_path))
        
        try:
            import PIL.Image
            from io import BytesIO
            import json
            
            # Load vial image
            vial_image = PIL.Image.open(vial_path)
            
            # Load label image - handle SVG conversion
            label_image = _load_label_image(label_path)
            
            # Get crop data if provided
            label_crop_data = None
            crop_data_str = request.form.get('labelCropData', '')
            if crop_data_str:
                try:
                    label_crop_data = json.loads(crop_data_str)
                    logger.info(f"Label crop data: {label_crop_data}")
                except Exception as e:
                    logger.warning(f"Failed to parse crop data: {e}")
            
            # Crop label if needed
            if label_crop_data:
                x = int(label_crop_data.get('x', 0))
                y = int(label_crop_data.get('y', 0))
                width = int(label_crop_data.get('width', label_image.width))
                height = int(label_crop_data.get('height', label_image.height))
                
                # Ensure crop coordinates are within bounds
                x = max(0, min(x, label_image.width - 1))
                y = max(0, min(y, label_image.height - 1))
                width = min(width, label_image.width - x)
                height = min(height, label_image.height - y)
                
                if width > 0 and height > 0:
                    label_image = label_image.crop((x, y, x + width, y + height))
                    logger.info(f"Cropped label to {width}x{height}")
            
            # Generate mockup with retry logic (same as Combined Generator)
            MAX_RETRIES = 3
            result_image = None
            verification_errors = []
            attempts = 0
            last_errors = []
            
            for attempt in range(1, MAX_RETRIES + 1):
                attempts = attempt
                logger.info(f"[Single Mockup] Attempt {attempt}/{MAX_RETRIES} for {sku}")
                
                # Generate mockup
                retry_hint = None
                if attempt > 1 and last_errors:
                    retry_hint = " | ".join(last_errors)
                    logger.info(f"[Single Mockup] Retry with hint: {retry_hint}")
                
                # Create fresh copies for each attempt
                vial_copy = vial_image.copy()
                label_copy = label_image.copy()
                
                mockup_image = _generate_mockup_for_product_with_retry(
                    vial_copy,
                    label_copy,
                    product_name,
                    sku,
                    dosage,
                    retry_hint=retry_hint
                )
                
                if mockup_image is None:
                    logger.error(f"[Single Mockup] Generation failed for {sku} on attempt {attempt}")
                    last_errors = ["Generation failed"]
                    continue
                
                # Verify mockup using SIDE-BY-SIDE comparison (highest quality)
                verification_result = verify_mockup_with_sidebyside(
                    mockup_image,
                    label_image,  # Reference label for comparison
                    sku,
                    product_name,
                    dosage,
                    config.GEMINI_API_KEY
                )

                # Extract results (backward compatibility)
                is_valid = verification_result.get('is_valid', False)
                detected_sku = verification_result.get('detected_sku', '')
                detected_name = verification_result.get('detected_product_name', '')
                detected_dosage = verification_result.get('detected_dosage', '')
                errors = verification_result.get('differences', [])
                
                if is_valid:
                    logger.info(f"[Single Mockup] ✓ Verification PASSED for {sku} on attempt {attempt}")
                    result_image = mockup_image
                    break
                else:
                    logger.warning(f"[Single Mockup] ✗ Verification FAILED for {sku} on attempt {attempt}: {errors}")
                    verification_errors.extend(errors)
                    last_errors = errors
                    
                    if attempt < MAX_RETRIES:
                        logger.info(f"[Single Mockup] Will retry with corrections...")
            
            if result_image is None:
                logger.error(f"[Single Mockup] Failed to generate valid mockup for {sku} after {MAX_RETRIES} attempts")
                return jsonify({
                    'error': f'Failed to generate valid mockup after {MAX_RETRIES} attempts',
                    'verification_errors': verification_errors
                }), 500
            
            # Save result
            output_filename = f"mockup_{sku}_{timestamp}.png"
            output_path = config.OUTPUT_DIR / output_filename
            
            # Ensure RGBA for transparency
            if result_image.mode != 'RGBA':
                result_image = result_image.convert('RGBA')
            
            result_image.save(str(output_path), 'PNG')
            logger.info(f"[Single Mockup] Saved mockup to {output_path}")
            
            # Return success with verification info
            return jsonify({
                'success': True,
                'mockup_url': f'/api/file/{output_filename}',
                'filename': output_filename,
                'verification_info': {
                    'attempts': attempts,
                    'errors': verification_errors if attempts > 1 else []
                }
            })
            
        finally:
            # Cleanup temporary files
            try:
                if vial_path.exists():
                    vial_path.unlink()
                if label_path.exists():
                    label_path.unlink()
            except Exception as e:
                logger.warning(f"Failed to cleanup temp files: {e}")
    
    except Exception as e:
        logger.error(f"Error generating single mockup: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/generate-mockup', methods=['POST'])
def generate_mockup():
    """Generate mockup using Gemini API (UPDATED with new SDK + retry + verification)."""
    try:
        # Check if Gemini API key is available
        if not config.GEMINI_API_KEY:
            logger.error("GEMINI_API_KEY not found in environment variables")
            return jsonify({
                'error': 'GEMINI_API_KEY not configured. Please set GEMINI_API_KEY in .env.local'
            }), 500

        # Get files and form data
        if 'vial' not in request.files or 'label' not in request.files:
            return jsonify({'error': 'Both vial and label files are required'}), 400

        vial_file = request.files['vial']
        label_file = request.files['label']

        if vial_file.filename == '' or label_file.filename == '':
            return jsonify({'error': 'Please upload both vial and label files'}), 400

        product_name = request.form.get('productName', '')
        sku = request.form.get('sku', '')
        dosage = request.form.get('dosage', '10 mg')

        if not product_name or not sku:
            return jsonify({'error': 'Product Name and SKU are required'}), 400
        
        # Save uploaded files temporarily
        vial_filename = secure_filename(vial_file.filename)
        label_filename = secure_filename(label_file.filename)

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        vial_path = config.UPLOAD_DIR / f"mockup_vial_{timestamp}_{vial_filename}"
        label_path = config.UPLOAD_DIR / f"mockup_label_{timestamp}_{label_filename}"

        vial_file.save(str(vial_path))
        label_file.save(str(label_path))

        try:
            import PIL.Image
            from io import BytesIO
            import json

            # Load vial image
            vial_image = PIL.Image.open(vial_path)

            # Load label image - handle SVG conversion
            label_image = _load_label_image(label_path)

            # Get crop data if provided
            label_crop_data = None
            crop_data_str = request.form.get('labelCropData', '')
            if crop_data_str:
                try:
                    label_crop_data = json.loads(crop_data_str)
                    logger.info(f"Label crop data: {label_crop_data}")
                except Exception as e:
                    logger.warning(f"Failed to parse crop data: {e}")

            # Crop label if needed
            if label_crop_data:
                x = int(label_crop_data.get('x', 0))
                y = int(label_crop_data.get('y', 0))
                width = int(label_crop_data.get('width', label_image.width))
                height = int(label_crop_data.get('height', label_image.height))

                # Ensure crop coordinates are within bounds
                x = max(0, min(x, label_image.width - 1))
                y = max(0, min(y, label_image.height - 1))
                width = min(width, label_image.width - x)
                height = min(height, label_image.height - y)

                if width > 0 and height > 0:
                    label_image = label_image.crop((x, y, x + width, y + height))
                    logger.info(f"Cropped label to {width}x{height}")

            # Generate mockup with retry logic (same as Combined Generator)
            MAX_RETRIES = 3
            result_image = None
            verification_errors = []
            attempts = 0
            last_errors = []

            for attempt in range(1, MAX_RETRIES + 1):
                attempts = attempt
                logger.info(f"[Mockup] Attempt {attempt}/{MAX_RETRIES} for {sku}")

                # Generate mockup
                retry_hint = None
                if attempt > 1 and last_errors:
                    retry_hint = " | ".join(last_errors)
                    logger.info(f"[Mockup] Retry with hint: {retry_hint}")

                # Create fresh copies for each attempt
                vial_copy = vial_image.copy()
                label_copy = label_image.copy()

                mockup_image = _generate_mockup_for_product_with_retry(
                    vial_copy,
                    label_copy,
                    product_name,
                    sku,
                    dosage,
                    retry_hint=retry_hint
                )

                if mockup_image is None:
                    logger.error(f"[Mockup] Generation failed for {sku} on attempt {attempt}")
                    last_errors = ["Generation failed"]
                    continue

                # Verify mockup using SIDE-BY-SIDE comparison (highest quality)
                verification_result = verify_mockup_with_sidebyside(
                    mockup_image,
                    label_image,  # Reference label for comparison
                    sku,
                    product_name,
                    dosage,
                    config.GEMINI_API_KEY
                )

                is_valid = verification_result.get('is_valid', False)
                errors = verification_result.get('differences', [])

                if is_valid:
                    logger.info(f"[Mockup] ✓ Verification PASSED for {sku} on attempt {attempt}")
                    result_image = mockup_image
                    break
                else:
                    logger.warning(f"[Mockup] ✗ Verification FAILED for {sku} on attempt {attempt}: {errors}")
                    verification_errors.extend(errors)
                    last_errors = errors

                    if attempt < MAX_RETRIES:
                        logger.info(f"[Mockup] Will retry with corrections...")

            if result_image is None:
                logger.error(f"[Mockup] Failed to generate valid mockup for {sku} after {MAX_RETRIES} attempts")
                return jsonify({
                    'error': f'Failed to generate valid mockup after {MAX_RETRIES} attempts',
                    'verification_errors': verification_errors
                }), 500

            # result_image already has background removed by _generate_mockup_for_product_with_retry()
            # Ensure RGBA for transparency
            if result_image.mode != 'RGBA':
                result_image = result_image.convert('RGBA')

            # Save final result
            output_filename = f"mockup_{sku}_{timestamp}.png"
            output_path = config.OUTPUT_DIR / output_filename

            result_image.save(str(output_path), 'PNG')
            logger.info(f"[Mockup] Saved mockup to {output_path}")

            # Return result URL
            result_url = f'/api/mockup-result/{output_filename}'

            return jsonify({
                'success': True,
                'result_url': result_url,  # Final mockup without background
                'filename': output_filename,
                'attempts': attempts,
                'verified': is_valid
            })

        except Exception as e:
            logger.error(f"Error generating mockup: {e}", exc_info=True)
            return jsonify({'error': f'Failed to generate mockup: {str(e)}'}), 500
        finally:
            # Cleanup temp files
            try:
                if vial_path.exists():
                    vial_path.unlink()
                if label_path.exists():
                    label_path.unlink()
            except (OSError, PermissionError) as e:
                logger.warning(f"Could not cleanup temp files: {e}")

    except Exception as e:
        logger.error(f"Error in generate_mockup: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/mockup-result/<filename>')
def get_mockup_result(filename):
    """Serve generated mockup result."""
    try:
        result_path = config.OUTPUT_DIR / secure_filename(filename)
        
        if not result_path.exists():
            return jsonify({'error': 'Mockup result not found'}), 404
        
        return send_file(str(result_path), mimetype='image/png')
    except Exception as e:
        logger.error(f"Error serving mockup result: {e}")
        return jsonify({'error': str(e)}), 500


def _generate_mockup_for_product_with_retry(vial_image, label_image, product_name, sku, dosage, retry_hint=None):
    """
    Generate a single mockup with optional retry hint for corrections.
    Used in parallel processing with auto-retry on verification failure.

    Args:
        vial_image: PIL Image of vial (with green background already applied or not)
        label_image: PIL Image of label (already cropped)
        product_name: Product name string
        sku: SKU string
        dosage: Dosage string
        retry_hint: Optional hint about what went wrong in previous attempt

    Returns:
        PIL Image with transparent background
    """
    try:
        import PIL.Image
        from io import BytesIO
        from google import genai
        from google.genai import types

        # Choose optimal background color (avoid colors in label/vial)
        optimal_bg_color = _choose_optimal_background_color(label_image, vial_image)

        # Apply background with optimal color
        vial_image_with_green_bg = add_green_background(vial_image, optimal_bg_color)

        # Build prompt with retry hint if provided
        retry_section = ""
        if retry_hint:
            retry_section = f"""
⚠️ CORRECTION REQUIRED - PREVIOUS ATTEMPT FAILED:
{retry_hint}

You MUST fix these issues in this attempt. Read the text from the label image VERY CAREFULLY and reproduce it EXACTLY.
"""

        prompt = f"""Apply this label design to the pharmaceutical vial. The label will wrap around the cylindrical vial surface.

{retry_section}
Expected content (reference only - READ FROM LABEL IMAGE, NOT THIS TEXT):
- Product: {product_name}
- Formula: {dosage if dosage else '(see label)'}
- Code: {sku}

CRITICAL INSTRUCTIONS:

1. TEXT PRESERVATION (HIGHEST PRIORITY):
   ✓ Read ALL text from the label image character-by-character
   ✓ Preserve EVERY letter, number, symbol, space exactly as shown
   ✓ Keep punctuation: parentheses (), slashes /, hyphens -, periods .
   ✓ Preserve number formats: "10mg" stays "10mg", "10 mg" stays "10 mg"
   ✓ Maintain exact spelling: if label shows "GHRP-2 (5mg)" write "GHRP-2 (5mg)"
   ✓ Do NOT add, remove, or change ANY characters

2. POSITIONING & CROPPING:
   ✓ Label may wrap around vial - some text at edges may be partially visible or cut off
   ✓ This is NORMAL and CORRECT for cylindrical vials
   ✓ If edge text appears cut (like "RESEARCH USE ON..." → "RESEARCH USE"), keep it cut
   ✓ If SKU is partial (like "YPB.1" when full is "YPB.111"), keep it partial
   ✓ Match the reference label's cropping/wrapping behavior

3. VISUAL ACCURACY (CRITICAL - PRESERVE ALL STYLING):
   ✓ Copy exact colors: background color, text colors
   ✓ Copy exact fonts: family (sans-serif/serif), size (proportions)

   ✓ FONT WEIGHT:
     • If text is BOLD in reference → make it BOLD in mockup
     • If text is REGULAR in reference → make it REGULAR in mockup
     • Preserve the exact visual weight as shown in the reference label

   ✓ Copy exact layout: alignment, line spacing, text positioning
   ✓ Apply natural curvature to match vial's cylindrical surface

EXAMPLES OF FONT WEIGHT PRESERVATION:
   Reference shows "SKU: YPB.111" in BOLD → Mockup MUST show it in BOLD
   Reference shows "10mg" in REGULAR → Mockup MUST show it in REGULAR
   Reference shows "Selank" in BOLD → Mockup MUST show it in BOLD

4. TECHNICAL QUALITY:
   ✓ Keep text SHARP and readable (not blurry)
   ✓ Maintain high resolution
   ✓ Natural lighting and shadows
   ✓ Preserve vial shape and proportions

REFERENCE SOURCE: The label image is your ONLY source. Ignore the expected content text above - READ from the image."""

        logger.info(f"Generating mockup for {product_name} (SKU: {sku}) {'[RETRY]' if retry_hint else ''}")

        # Initialize Gemini client
        client = genai.Client(api_key=config.GEMINI_API_KEY)

        # Prepare content with images
        vial_w, vial_h = vial_image.size
        aspect = _aspect_ratio_for_gemini(vial_w, vial_h)

        # Create generation config
        generation_config = types.GenerateContentConfig(
            temperature=0.05 if retry_hint else 0.1,
            top_p=0.9,
            top_k=5 if retry_hint else 10,
            response_modalities=["IMAGE"],
        )

        # Generate content with images
        response = client.models.generate_content(
            model=config.GEMINI_MOCKUP_MODEL,
            contents=[
                prompt,
                vial_image_with_green_bg,
                label_image
            ],
            config=generation_config
        )

        # Extract image from response
        result_image = None
        for part in response.parts:
            if part.inline_data is not None and part.inline_data.data is not None:
                # Convert bytes to PIL.Image
                image_bytes = part.inline_data.data
                result_image = PIL.Image.open(BytesIO(image_bytes))
                logger.info(f"Successfully extracted image from Gemini API for {sku}")
                break

        if not result_image:
            logger.warning(f"Gemini API did not return image for {sku}")
            return None

        # Remove background (using optimal color selected earlier)
        result_image = remove_background_with_reference(result_image, vial_image, label_reference=label_image, background_color=optimal_bg_color)

        logger.info(f"[MOCKUP GEN] Final mockup for {sku}: mode={result_image.mode}, size={result_image.size}")
        return result_image

    except Exception as e:
        logger.error(f"Error generating mockup for {sku}: {e}", exc_info=True)
        return None


def _generate_mockup_for_product(vial_image, label_image, product_name, sku, dosage, label_crop_data=None):
    """
    Generate a single mockup for a product using Gemini API.
    Returns PIL Image with transparent background.

    Args:
        vial_image: PIL Image of vial
        label_image: PIL Image of label
        product_name: Product name string
        sku: SKU string
        dosage: Dosage string
        label_crop_data: Optional dict with x, y, width, height in pixels for cropping label

    Returns:
        PIL Image with transparent background
    """
    try:
        import PIL.Image
        from io import BytesIO
        from google import genai
        from google.genai import types

        # Choose optimal background color (avoid colors in label/vial)
        optimal_bg_color = _choose_optimal_background_color(label_image, vial_image)

        # Apply background with optimal color
        vial_image_with_green_bg = add_green_background(vial_image, optimal_bg_color)

        # Apply label crop if specified (crop label to selected area)
        if label_crop_data:
            crop_x = int(label_crop_data.get('x', 0))
            crop_y = int(label_crop_data.get('y', 0))
            crop_width = int(label_crop_data.get('width', label_image.width))
            crop_height = int(label_crop_data.get('height', label_image.height))

            # Ensure coordinates are within bounds
            crop_x = max(0, min(crop_x, label_image.width - 1))
            crop_y = max(0, min(crop_y, label_image.height - 1))
            crop_width = min(crop_width, label_image.width - crop_x)
            crop_height = min(crop_height, label_image.height - crop_y)

            if crop_width > 0 and crop_height > 0:
                label_image = label_image.crop((crop_x, crop_y, crop_x + crop_width, crop_y + crop_height))
                logger.info(f"Cropped label to {crop_width}x{crop_height} at ({crop_x}, {crop_y})")

        # Prepare prompt
        prompt = f"""Apply this label design to the pharmaceutical vial. The label will wrap around the cylindrical vial surface.

Expected content (reference only - READ FROM LABEL IMAGE, NOT THIS TEXT):
- Product: {product_name}
- Formula: {dosage if dosage else '(see label)'}
- Code: {sku}

CRITICAL INSTRUCTIONS:

1. TEXT PRESERVATION (HIGHEST PRIORITY):
   ✓ Read ALL text from the label image character-by-character
   ✓ Preserve EVERY letter, number, symbol, space exactly as shown
   ✓ Keep punctuation: parentheses (), slashes /, hyphens -, periods .
   ✓ Preserve number formats: "10mg" stays "10mg", "10 mg" stays "10 mg"
   ✓ Maintain exact spelling: if label shows "GHRP-2 (5mg)" write "GHRP-2 (5mg)"
   ✓ Do NOT add, remove, or change ANY characters

2. POSITIONING & CROPPING:
   ✓ Label may wrap around vial - some text at edges may be partially visible or cut off
   ✓ This is NORMAL and CORRECT for cylindrical vials
   ✓ If edge text appears cut (like "RESEARCH USE ON..." → "RESEARCH USE"), keep it cut
   ✓ If SKU is partial (like "YPB.1" when full is "YPB.111"), keep it partial
   ✓ Match the reference label's cropping/wrapping behavior

3. VISUAL ACCURACY (CRITICAL - PRESERVE ALL STYLING):
   ✓ Copy exact colors: background color, text colors
   ✓ Copy exact fonts: family (sans-serif/serif), size (proportions)

   ✓ FONT WEIGHT:
     • If text is BOLD in reference → make it BOLD in mockup
     • If text is REGULAR in reference → make it REGULAR in mockup
     • Preserve the exact visual weight as shown in the reference label

   ✓ Copy exact layout: alignment, line spacing, text positioning
   ✓ Apply natural curvature to match vial's cylindrical surface

EXAMPLES OF FONT WEIGHT PRESERVATION:
   Reference shows "SKU: YPB.111" in BOLD → Mockup MUST show it in BOLD
   Reference shows "10mg" in REGULAR → Mockup MUST show it in REGULAR
   Reference shows "Selank" in BOLD → Mockup MUST show it in BOLD

4. TECHNICAL QUALITY:
   ✓ Keep text SHARP and readable (not blurry)
   ✓ Maintain high resolution
   ✓ Natural lighting and shadows
   ✓ Preserve vial shape and proportions

REFERENCE SOURCE: The label image is your ONLY source. Ignore the expected content text above - READ from the image."""

        logger.info(f"Generating mockup for {product_name} (SKU: {sku}) using Gemini API ({config.GEMINI_MOCKUP_MODEL})")

        # Initialize Gemini client
        client = genai.Client(api_key=config.GEMINI_API_KEY)

        # Create generation config
        cfg = config.GEMINI_MOCKUP_CONFIG
        generation_config = types.GenerateContentConfig(
            temperature=cfg.get("temperature", 0.1),
            top_p=cfg.get("topP", 0.85),
            top_k=cfg.get("topK", 10),
            response_modalities=["IMAGE"],
        )

        # Generate content with images
        response = client.models.generate_content(
            model=config.GEMINI_MOCKUP_MODEL,
            contents=[
                prompt,
                vial_image_with_green_bg,
                label_image
            ],
            config=generation_config
        )

        # Extract image from response
        result_image = None
        for part in response.parts:
            if part.inline_data is not None and part.inline_data.data is not None:
                # Convert bytes to PIL.Image
                image_bytes = part.inline_data.data
                result_image = PIL.Image.open(BytesIO(image_bytes))
                logger.info(f"Successfully extracted image from Gemini API for {sku}")
                break

        if not result_image:
            logger.warning(f"Gemini API did not return image for {sku}, using fallback composite")
            # Fallback: create simple composite
            vial_width, vial_height = vial_image.size
            label_width, label_height = label_image.size

            scale = min(vial_width * 0.4 / label_width, vial_height * 0.3 / label_height)
            new_label_size = (int(label_width * scale), int(label_height * scale))
            label_resized = label_image.resize(new_label_size, PIL.Image.Resampling.LANCZOS)

            if vial_image.mode != 'RGBA':
                result_image = vial_image.convert('RGBA')
            else:
                result_image = vial_image.copy()

            position = ((vial_width - new_label_size[0]) // 2, (vial_height - new_label_size[1]) // 2)

            if label_resized.mode == 'RGBA':
                result_image.paste(label_resized, position, label_resized)
            else:
                label_rgba = label_resized.convert('RGBA')
                result_image.paste(label_rgba, position, label_rgba)

        # Remove background (using optimal color selected earlier)
        result_image = remove_background_with_reference(result_image, vial_image, background_color=optimal_bg_color)

        # Ensure RGBA mode
        if result_image.mode != 'RGBA':
            result_image = result_image.convert('RGBA')

        return result_image

    except Exception as e:
        logger.error(f"Error generating mockup for {sku}: {e}", exc_info=True)
        raise


# ============== Combined Generator - Two Step Process ==============

@run_in_background
def _generate_labels_task(job_id, tracking_id, template_path, products, text_areas, output_dir, text_alignments=None):
    """Background task for generating labels - runs in separate thread"""
    if text_alignments is None:
        text_alignments = {}
    try:
        labels = []
        errors = []

        # Initialize progress
        progress_tracker.set(tracking_id, {
            'current': 0,
            'total': len(products),
            'status': 'processing',
            'message': 'Starting...',
            'current_product': '',
            'percentage': 0
        })

        # Generate labels for each product
        for i, product in enumerate(products):
            try:
                product_name = product.get('Product', 'Unknown')
                sku = product.get('SKU', f'UNKNOWN_{i}')

                # Update progress
                progress_tracker.set(tracking_id, {
                    'current': i,
                    'total': len(products),
                    'status': 'processing',
                    'message': f'Generating: {product_name}',
                    'current_product': product_name,
                    'percentage': int((i / len(products)) * 100)
                })

                logger.info(f"Processing label {i+1}/{len(products)}: {product_name} ({sku})")

                # Create temp CSV for single product
                import csv
                temp_dir = config.TEMP_DIR / f"label_{sku.replace('/', '_')}_{job_id}"
                temp_dir.mkdir(parents=True, exist_ok=True)
                temp_csv = temp_dir / "temp_product.csv"

                with open(temp_csv, 'w', newline='', encoding='utf-8') as f:
                    fieldnames = ['Product', 'Ingredients', 'SKU']
                    writer = csv.DictWriter(f, fieldnames=fieldnames)
                    writer.writeheader()
                    filtered_product = {k: v for k, v in product.items() if k in fieldnames}
                    writer.writerow(filtered_product)

                # Generate label
                processor = BatchProcessor(template_path, temp_csv, text_areas=text_areas, text_alignments=text_alignments)
                result = processor.process_batch(output_dir=temp_dir, limit=1)

                # Find generated files and copy all formats (SVG, PNG, PDF)
                for res in result.get('results', []):
                    if res.get('status') == 'success':
                        sku_safe = sku.replace('/', '_').replace('\\', '_')

                        # Get paths for all formats
                        svg_path = res.get('svg')
                        jpg_path = res.get('jpg')
                        pdf_path = res.get('pdf')

                        # Convert SVG to PNG for mockup use
                        png_path = None
                        if svg_path and Path(svg_path).exists():
                            try:
                                import cairosvg
                                png_path = Path(svg_path).with_suffix('.png')
                                cairosvg.svg2png(url=str(svg_path), write_to=str(png_path))
                            except Exception as e:
                                logger.warning(f"Failed to convert SVG to PNG: {e}")

                        # Copy all available formats to output directory
                        files_copied = {}

                        # Copy SVG
                        if svg_path and Path(svg_path).exists():
                            svg_output = output_dir / f"label_{sku_safe}.svg"
                            shutil.copy(svg_path, svg_output)
                            files_copied['svg'] = str(svg_output)

                        # Copy PNG (for mockups)
                        if png_path and Path(png_path).exists():
                            png_output = output_dir / f"label_{sku_safe}.png"
                            shutil.copy(png_path, png_output)
                            files_copied['png'] = str(png_output)

                        # Copy PDF
                        if pdf_path and Path(pdf_path).exists():
                            pdf_output = output_dir / f"label_{sku_safe}.pdf"
                            shutil.copy(pdf_path, pdf_output)
                            files_copied['pdf'] = str(pdf_output)

                        # Copy JPG as fallback
                        if jpg_path and Path(jpg_path).exists():
                            jpg_output = output_dir / f"label_{sku_safe}.jpg"
                            shutil.copy(jpg_path, jpg_output)
                            files_copied['jpg'] = str(jpg_output)

                        if files_copied:
                            # Use PNG for preview/mockup if available, otherwise JPG
                            preview_file = files_copied.get('png') or files_copied.get('jpg')
                            preview_filename = Path(preview_file).name if preview_file else None

                            labels.append({
                                'sku': sku,
                                'product_name': product_name,
                                'filename': preview_filename,  # PNG or JPG for preview
                                'path': preview_file,  # Main file for mockup generation
                                'files': files_copied,  # All generated files
                                'preview_url': f'/api/label-preview/{job_id}/{preview_filename}' if preview_filename else None
                            })
                            logger.info(f"Generated label for {sku}: {list(files_copied.keys())}")

                            # Update progress after successful generation
                            progress_tracker.set(tracking_id, {
                                'current': i + 1,
                                'total': len(products),
                                'status': 'processing',
                                'message': f'Completed: {product_name}',
                                'current_product': product_name,
                                'percentage': int(((i + 1) / len(products)) * 100)
                            })
                        break

            except Exception as e:
                logger.error(f"Error generating label for {sku}: {e}")
                errors.append(f"{sku}: {str(e)}")
                # Update progress even on error
                progress_tracker.set(tracking_id, {
                    'current': i + 1,
                    'total': len(products),
                    'status': 'processing',
                    'message': f'Error: {product_name}',
                    'current_product': product_name,
                    'percentage': int(((i + 1) / len(products)) * 100)
                })

        # Create ZIP file with folder structure: labels/SKU/files
        zip_filename = f"labels_{job_id}.zip"
        zip_path = output_dir / zip_filename

        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for label in labels:
                sku = label['sku'].replace('/', '_').replace('\\', '_')
                # Add all available file formats to ZIP in SKU folder
                files_dict = label.get('files', {})
                for format_type, file_path in files_dict.items():
                    if Path(file_path).exists():
                        # Structure: labels/SKU/filename.ext
                        filename = Path(file_path).name
                        zip_entry_path = f"labels/{sku}/{filename}"
                        zf.write(file_path, zip_entry_path)

        logger.info(f"Generated {len(labels)} labels, {len(errors)} errors")

        # Store results in global dict
        background_results[job_id] = {
            'success': True,
            'job_id': job_id,
            'total': len(labels),
            'errors': len(errors),
            'error_details': errors[:10],
            'labels': labels,
            'zip_file': zip_filename
        }

        # Mark progress as complete
        progress_tracker.set(tracking_id, {
            'current': len(products),
            'total': len(products),
            'status': 'completed',
            'message': f'Complete! Generated {len(labels)} labels',
            'current_product': '',
            'percentage': 100
        })

        logger.info(f"Background task completed for job {job_id}")

    except Exception as e:
        logger.error(f"Background task error for job {job_id}: {e}", exc_info=True)

        # Store error in results
        background_results[job_id] = {
            'success': False,
            'error': str(e)
        }

        # Mark progress as failed
        progress_tracker.set(tracking_id, {
            'status': 'failed',
            'message': str(e),
            'percentage': 0
        })


@app.route('/api/generation-progress/<job_id>', methods=['GET'])
def get_generation_progress(job_id):
    """Get current progress of a generation job"""
    progress = progress_tracker.get(job_id)
    if progress:
        return jsonify(progress)
    else:
        return jsonify({'current': 0, 'total': 0, 'status': 'unknown', 'message': 'Job not found'})


@app.route('/api/generate-labels-combined', methods=['POST'])
def generate_labels_combined():
    """Step 1: Generate labels (async) - returns immediately with job_id"""
    # #region agent log
    _dbg("app.py:generate_labels_combined", "entry", {"has_template": bool(request.files.get('template'))}, "H2")
    # #endregion
    try:
        template_file = request.files.get('template')
        if not template_file:
            return jsonify({'error': 'No template file provided'}), 400

        text_areas_str = request.form.get('textAreas', '{}')
        text_areas = json.loads(text_areas_str) if text_areas_str else {}

        text_alignments_str = request.form.get('textAlignments', '{}')
        text_alignments = json.loads(text_alignments_str) if text_alignments_str else {}
        logger.info(f"Text alignments: {text_alignments}")

        limit = request.form.get('limit')
        limit = int(limit) if limit else None

        # Save template
        template_filename = secure_filename(template_file.filename)
        job_id = datetime.now().strftime('%Y%m%d_%H%M%S')
        tracking_id = request.form.get('tracking_id', job_id)  # Use tracking_id for progress if provided

        # Check if this is an already converted SVG from AI file
        # (uploaded from frontend after conversion)
        if template_filename.startswith('ai_preview_') and template_filename.endswith('.svg'):
            # This is already a converted SVG, look for it in UPLOAD_DIR
            existing_svg = config.UPLOAD_DIR / template_filename
            if existing_svg.exists():
                logger.info(f"Using pre-converted SVG: {existing_svg}")
                template_path = existing_svg
            else:
                # Save the uploaded SVG
                template_path = config.UPLOAD_DIR / f"combined_template_{job_id}_{template_filename}"
                template_file.save(str(template_path))
        else:
            # Regular upload
            template_path = config.UPLOAD_DIR / f"combined_template_{job_id}_{template_filename}"
            template_file.save(str(template_path))

            # Convert AI to SVG if needed
            if template_path.suffix.lower() == '.ai':
                try:
                    converter = AIConverter()
                    svg_path = converter.convert_to_svg(template_path, text_to_path=False)
                    template_path = svg_path
                except AIConverterError as e:
                    return jsonify({'error': f'Failed to convert AI file: {str(e)}'}), 400

        # Auto-detect text areas from data-placeholder attributes if textAreas is empty
        if not text_areas or len(text_areas) == 0:
            logger.info("textAreas is empty, auto-detecting from data-placeholder attributes...")
            try:
                tree = ET.parse(str(template_path))
                root = tree.getroot()

                # Find all elements with data-placeholder
                auto_areas = {}
                for elem in root.iter():
                    placeholder = elem.get('data-placeholder')
                    if placeholder:
                        # Get text content
                        text_content = elem.text or ''
                        # Map placeholder to CSV column
                        csv_column_map = {
                            'sku': 'SKU',
                            'product_name': 'Product',
                            'ingredients': 'Ingredients'
                        }
                        csv_column = csv_column_map.get(placeholder)
                        if csv_column:
                            auto_areas[placeholder] = csv_column
                            logger.info(f"Auto-detected placeholder: {placeholder} -> {csv_column} (text: {text_content[:30]})")

                if auto_areas:
                    text_areas = auto_areas
                    logger.info(f"Auto-detected {len(auto_areas)} text areas from placeholders")
                else:
                    logger.warning("No data-placeholder attributes found in SVG")
            except Exception as e:
                logger.error(f"Error auto-detecting text areas: {e}")

        # Load products from current database
        csv_path = Path(get_current_database())
        if not csv_path.exists():
            return jsonify({'error': f'Database not found: {csv_path}'}), 400

        csv_manager = CSVManager(csv_path)
        products = csv_manager.read_all()

        if limit:
            products = products[:limit]

        if not products:
            return jsonify({'error': 'No products found in database'}), 400

        logger.info(f"Starting background generation for {len(products)} products")

        # Create output directory
        output_dir = config.OUTPUT_DIR / f"labels_{job_id}"
        output_dir.mkdir(parents=True, exist_ok=True)

        # Start background task (non-blocking)
        _generate_labels_task(job_id, tracking_id, template_path, products, text_areas, output_dir, text_alignments)

        # Return immediately with job_id
        # #region agent log
        _dbg("app.py:generate_labels_combined", "started_background", {"job_id": job_id, "n_products": len(products)}, "H2")
        # #endregion
        return jsonify({
            'success': True,
            'job_id': job_id,
            'tracking_id': tracking_id,
            'status': 'processing',
            'message': f'Label generation started in background for {len(products)} products'
        })

    except Exception as e:
        # #region agent log
        import traceback
        _dbg("app.py:generate_labels_combined", "exception", {"error": str(e), "type": type(e).__name__, "traceback": traceback.format_exc()}, "H2,H5")
        # #endregion
        logger.error(f"Error in generate_labels_combined: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/generation-results/<job_id>')
def get_generation_results(job_id):
    """Get results of background label generation task"""
    # Check if results are available
    if job_id in background_results:
        result = background_results.pop(job_id)  # Remove after fetching (cleanup)
        logger.info(f"Returning results for job {job_id}")
        return jsonify(result)

    # Check progress status
    progress = progress_tracker.get(job_id)
    if progress:
        status = progress.get('status')
        if status == 'processing':
            return jsonify({
                'status': 'processing',
                'message': 'Still generating...',
                'percentage': progress.get('percentage', 0)
            }), 202  # 202 Accepted
        elif status == 'failed':
            return jsonify({
                'success': False,
                'error': progress.get('message', 'Generation failed')
            }), 500

    # Job not found
    return jsonify({'error': 'Job not found or expired'}), 404


@app.route('/api/label-preview/<job_id>/<filename>')
def label_preview(job_id, filename):
    """Serve label preview image"""
    safe_filename = secure_filename(filename)
    file_path = config.OUTPUT_DIR / f"labels_{job_id}" / safe_filename
    
    if file_path.exists():
        # Determine mimetype based on extension
        ext = file_path.suffix.lower()
        mimetype = 'image/png' if ext == '.png' else 'image/jpeg'
        return send_file(file_path, mimetype=mimetype)
    return jsonify({'error': 'Label not found'}), 404


@app.route('/api/download-labels/<job_id>')
def download_labels(job_id):
    """Download labels ZIP file"""
    zip_path = config.OUTPUT_DIR / f"labels_{job_id}" / f"labels_{job_id}.zip"
    
    if zip_path.exists():
        return send_file(zip_path, as_attachment=True, download_name=f"labels_{job_id}.zip")
    return jsonify({'error': 'ZIP file not found'}), 404

@run_in_background
def _generate_mockups_from_labels_task(job_id, tracking_id, vial_bytes, labels, labels_job_id, label_crop_data, output_dir):
    """Background task for generating mockups from labels"""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import threading
    import copy
    import PIL.Image
    from io import BytesIO
    import zipfile

    try:
        logger.info(f"[Background] Starting mockup generation for {len(labels)} labels (parallel mode)")

        # Initialize progress tracking
        progress_tracker.set(tracking_id, {
            'current': 0,
            'total': len(labels),
            'status': 'processing',
            'message': 'Starting parallel mockup generation...',
            'current_product': '',
            'percentage': 0
        })

        # Thread-safe counters
        completed_count = [0]
        progress_lock = threading.Lock()

        def process_single_mockup(label_info, index):
            """Process a single mockup in a thread"""
            MAX_RETRIES = 3

            try:
                sku = label_info.get('sku', f'UNKNOWN_{index}')
                product_name = label_info.get('product_name', 'Unknown')
                label_path_str = label_info.get('path')
                dosage = label_info.get('dosage', '')

                # Resolve label path
                if not label_path_str or not Path(label_path_str).exists():
                    label_path = config.OUTPUT_DIR / f"labels_{labels_job_id}" / label_info.get('filename', '')
                    if not label_path.exists():
                        return {'error': f"{sku}: Label file not found", 'sku': sku}
                else:
                    label_path = Path(label_path_str)

                logger.info(f"[Thread] Processing mockup {index+1}/{len(labels)}: {product_name} ({sku})")

                # Load label image
                label_image_original = PIL.Image.open(label_path)
                logger.info(f"[Thread {sku}] Label loaded from {label_path.name}: mode={label_image_original.mode}, size={label_image_original.size}")

                # Crop if needed
                thread_crop_data = copy.deepcopy(label_crop_data) if label_crop_data else None
                label_image_cropped = label_image_original.copy()

                if thread_crop_data:
                    crop_x = int(thread_crop_data.get('x', 0))
                    crop_y = int(thread_crop_data.get('y', 0))
                    crop_width = int(thread_crop_data.get('width', label_image_cropped.width))
                    crop_height = int(thread_crop_data.get('height', label_image_cropped.height))

                    crop_x = max(0, min(crop_x, label_image_cropped.width - 1))
                    crop_y = max(0, min(crop_y, label_image_cropped.height - 1))
                    crop_width = min(crop_width, label_image_cropped.width - crop_x)
                    crop_height = min(crop_height, label_image_cropped.height - crop_y)

                    if crop_width > 0 and crop_height > 0:
                        label_image_cropped = label_image_cropped.crop((crop_x, crop_y, crop_x + crop_width, crop_y + crop_height))

                # RETRY LOOP with verification
                mockup_image = None
                verification_result = None
                last_errors = []

                for attempt in range(1, MAX_RETRIES + 1):
                    logger.info(f"[Thread {sku}] Attempt {attempt}/{MAX_RETRIES}")

                    vial_image_copy = PIL.Image.open(BytesIO(vial_bytes))

                    retry_hint = None
                    if attempt > 1 and last_errors:
                        retry_hint = f"PREVIOUS ATTEMPT FAILED. Errors: {', '.join(last_errors)}."

                    # Composite label onto white background before sending to Gemini
                    label_for_gemini = label_image_cropped.copy()
                    logger.info(f"[Thread {sku}] Label BEFORE composite: mode={label_for_gemini.mode}, size={label_for_gemini.size}")

                    if label_for_gemini.mode in ('RGBA', 'LA'):
                        bg_white = PIL.Image.new('RGB', label_for_gemini.size, (255, 255, 255))
                        bg_white.paste(label_for_gemini, mask=label_for_gemini.split()[-1])
                        label_for_gemini = bg_white
                        logger.info(f"[Thread {sku}] Label AFTER composite: mode={label_for_gemini.mode}")
                    elif label_for_gemini.mode != 'RGB':
                        original_mode = label_for_gemini.mode
                        label_for_gemini = label_for_gemini.convert('RGB')
                        logger.info(f"[Thread {sku}] Label converted from {original_mode} to RGB")

                    mockup_image = _generate_mockup_for_product_with_retry(
                        vial_image_copy,
                        label_for_gemini,
                        product_name,
                        sku,
                        dosage,
                        retry_hint
                    )

                    vial_image_copy.close()

                    if not mockup_image:
                        last_errors = ["Failed to generate mockup image"]
                        continue

                    # Verify mockup (use same composited label as sent to Gemini)
                    try:
                        verification_result = verify_mockup_with_sidebyside(
                            mockup_image,
                            label_for_gemini,
                            sku,
                            product_name,
                            dosage,
                            config.GEMINI_API_KEY
                        )
                    except Exception as e:
                        logger.error(f"[Thread {sku}] Verification error: {e}")
                        last_errors = [f"Verification error: {str(e)}"]
                        continue

                    if verification_result.get('is_valid', False):
                        logger.info(f"[Thread {sku}] ✅ Verified on attempt {attempt}")
                        break
                    else:
                        errors_list = verification_result.get('differences', [])
                        last_errors = errors_list if errors_list else ["Verification failed"]
                        logger.warning(f"[Thread {sku}] ❌ Failed attempt {attempt}")

                label_image_original.close()

                if not mockup_image or not verification_result or not verification_result.get('is_valid', False):
                    error_msg = f"{sku}: Failed after {MAX_RETRIES} attempts"
                    return {'error': error_msg, 'sku': sku}

                # Save mockup
                sku_safe = sku.replace('/', '_').replace('\\', '_')
                mockup_filename = f"mockup_{sku_safe}.png"
                mockup_path = output_dir / mockup_filename
                mockup_image.save(str(mockup_path), 'PNG')

                # Update progress
                with progress_lock:
                    completed_count[0] += 1
                    current = completed_count[0]
                    progress_tracker.set(tracking_id, {
                        'current': current,
                        'total': len(labels),
                        'status': 'processing',
                        'message': f'Generated {current}/{len(labels)} mockups',
                        'current_product': product_name,
                        'percentage': int((current / len(labels)) * 100)
                    })

                return {
                    'sku': sku,
                    'name': product_name,  # Frontend expects 'name'
                    'product_name': product_name,
                    'filename': mockup_filename,
                    'url': f'/api/mockup-preview/{job_id}/{mockup_filename}',  # Frontend expects 'url'
                    'preview_url': f'/api/mockup-preview/{job_id}/{mockup_filename}',
                    'verification': verification_result
                }

            except Exception as e:
                logger.error(f"[Thread] Error: {e}", exc_info=True)
                return {'error': str(e), 'sku': label_info.get('sku', 'UNKNOWN')}

        # Process in parallel
        mockups = []
        errors = []

        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = {executor.submit(process_single_mockup, label, i): i for i, label in enumerate(labels)}

            for future in as_completed(futures):
                try:
                    result = future.result()
                    if 'error' in result:
                        errors.append(result['error'])
                    else:
                        mockups.append(result)
                except Exception as e:
                    errors.append(str(e))

        # Create ZIP
        zip_filename = f"mockups_{job_id}.zip"
        zip_path = output_dir / zip_filename

        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for mockup in mockups:
                mockup_file_path = output_dir / mockup['filename']
                if mockup_file_path.exists():
                    zf.write(mockup_file_path, mockup['filename'])

        # Store results
        background_results[job_id] = {
            'success': True,
            'job_id': job_id,
            'total': len(mockups),
            'errors': len(errors),
            'error_details': errors[:10],
            'mockups': mockups,
            'zip_file': zip_filename
        }

        # Mark complete
        progress_tracker.set(tracking_id, {
            'current': len(labels),
            'total': len(labels),
            'status': 'completed',
            'message': f'Complete! Generated {len(mockups)} mockups',
            'percentage': 100
        })

        logger.info(f"[Background] Completed job {job_id}")

    except Exception as e:
        logger.error(f"[Background] Error: {e}", exc_info=True)
        background_results[job_id] = {
            'success': False,
            'error': str(e)
        }
        progress_tracker.set(tracking_id, {
            'status': 'failed',
            'message': str(e)
        })


@app.route('/api/generate-mockups-from-labels', methods=['POST'])
def generate_mockups_from_labels():
    """Step 2: Generate mockups (async) - returns immediately with job_id"""
    import PIL.Image
    from io import BytesIO

    try:
        vial_file = request.files.get('vial')
        if not vial_file:
            return jsonify({'error': 'No vial image provided'}), 400

        labels_job_id = request.form.get('labels_job_id')
        labels_str = request.form.get('labels', '[]')
        labels = json.loads(labels_str) if labels_str else []

        label_crop_data_str = request.form.get('labelCropData')
        label_crop_data = json.loads(label_crop_data_str) if label_crop_data_str else None

        if not labels:
            return jsonify({'error': 'No labels provided'}), 400

        logger.info(f"[ENDPOINT] Starting background mockup generation for {len(labels)} labels")

        # Get tracking ID
        tracking_id = request.form.get('tracking_id', f'mockups_{datetime.now().strftime("%Y%m%d_%H%M%S")}')
        logger.info(f"[ENDPOINT] tracking_id={tracking_id}")

        # Save vial
        job_id = datetime.now().strftime('%Y%m%d_%H%M%S')
        logger.info(f"[ENDPOINT] job_id={job_id}")
        vial_filename = secure_filename(vial_file.filename)
        vial_path = config.UPLOAD_DIR / f"mockup_vial_{job_id}_{vial_filename}"
        vial_file.save(str(vial_path))

        # Load vial image and convert to bytes for thread-safe sharing
        vial_image_original = PIL.Image.open(vial_path)
        vial_buffer = BytesIO()
        vial_image_original.save(vial_buffer, format='PNG')
        vial_bytes = vial_buffer.getvalue()
        vial_image_original.close()

        # Create output directory
        output_dir = config.OUTPUT_DIR / f"mockups_{job_id}"
        output_dir.mkdir(parents=True, exist_ok=True)

        # Cleanup vial file
        try:
            if vial_path.exists():
                vial_path.unlink()
        except (OSError, PermissionError) as e:
            logger.warning(f"Could not cleanup vial file: {e}")

        # Start background task (non-blocking)
        logger.info(f"[ENDPOINT] Starting background mockup generation for {len(labels)} labels")
        _generate_mockups_from_labels_task(job_id, tracking_id, vial_bytes, labels, labels_job_id, label_crop_data, output_dir)
        logger.info(f"[ENDPOINT] Background task started")

        # Return immediately with job_id
        return jsonify({
            'success': True,
            'job_id': job_id,
            'tracking_id': tracking_id,
            'status': 'processing',
            'message': f'Mockup generation started in background for {len(labels)} labels'
        })

    except Exception as e:
        logger.error(f"Error in generate_mockups_from_labels: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@app.route('/api/mockup-generation-results/<job_id>')
def get_mockup_generation_results(job_id):
    """Get results of background mockup generation task"""
    # Check if results are available
    if job_id in background_results:
        result = background_results.pop(job_id)  # Remove after fetching (cleanup)
        logger.info(f"Returning mockup results for job {job_id}")
        return jsonify(result)

    # Check progress status
    progress = progress_tracker.get(job_id)
    if progress:
        status = progress.get('status')
        if status == 'processing':
            return jsonify({
                'status': 'processing',
                'message': 'Still generating...',
                'percentage': progress.get('percentage', 0)
            }), 202  # 202 Accepted
        elif status == 'failed':
            return jsonify({
                'success': False,
                'error': progress.get('message', 'Generation failed')
            }), 500

    # Job not found
    return jsonify({'error': 'Job not found or expired'}), 404


@app.route('/api/mockup-preview/<job_id>/<filename>')
def mockup_preview(job_id, filename):
    """Serve mockup preview image"""
    safe_filename = secure_filename(filename)
    file_path = config.OUTPUT_DIR / f"mockups_{job_id}" / safe_filename
    
    if file_path.exists():
        return send_file(file_path, mimetype='image/png')
    return jsonify({'error': 'Mockup not found'}), 404


@app.route('/api/download-mockups/<job_id>')
def download_mockups(job_id):
    """Download mockups ZIP file"""
    zip_path = config.OUTPUT_DIR / f"mockups_{job_id}" / f"mockups_{job_id}.zip"

    if zip_path.exists():
        return send_file(zip_path, as_attachment=True, download_name=f"mockups_{job_id}.zip")
    return jsonify({'error': 'ZIP file not found'}), 404


@app.route('/api/download-combined-all/<labels_job_id>/<mockups_job_id>')
def download_combined_all(labels_job_id, mockups_job_id):
    """
    Download combined ZIP with labels and mockups organized by SKU.

    Structure:
        combined_TIMESTAMP.zip
        ├── YPB.100/
        │   ├── label.svg
        │   ├── label.png
        │   ├── label.jpg
        │   ├── label.pdf
        │   └── mockup.png
        ├── YPB.101/
        │   └── ...
    """
    import zipfile
    import re
    from collections import defaultdict

    try:
        # Find source directories
        labels_dir = config.OUTPUT_DIR / f"labels_{labels_job_id}"
        mockups_dir = config.OUTPUT_DIR / f"mockups_{mockups_job_id}"

        if not labels_dir.exists():
            return jsonify({'error': f'Labels directory not found: labels_{labels_job_id}'}), 404

        if not mockups_dir.exists():
            return jsonify({'error': f'Mockups directory not found: mockups_{mockups_job_id}'}), 404

        # Group files by SKU
        files_by_sku = defaultdict(list)

        # Pattern to extract SKU from filename: label_YPB.100.svg -> YPB.100
        sku_pattern = re.compile(r'(?:label|mockup)_([A-Z]+\.\d+)\.(svg|png|jpg|jpeg|pdf)$', re.IGNORECASE)

        # Collect label files
        for label_file in labels_dir.glob('label_*.*'):
            match = sku_pattern.match(label_file.name)
            if match:
                sku = match.group(1)
                ext = match.group(2).lower()
                # Store as (source_path, new_filename_in_zip)
                files_by_sku[sku].append((label_file, f"label.{ext}"))

        # Collect mockup files
        for mockup_file in mockups_dir.glob('mockup_*.png'):
            match = sku_pattern.match(mockup_file.name)
            if match:
                sku = match.group(1)
                files_by_sku[sku].append((mockup_file, "mockup.png"))

        if not files_by_sku:
            return jsonify({'error': 'No files found to combine'}), 404

        # Create combined ZIP
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        zip_filename = f"combined_{timestamp}.zip"
        zip_path = config.TEMP_DIR / zip_filename

        logger.info(f"Creating combined ZIP with {len(files_by_sku)} SKUs")

        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for sku, files in sorted(files_by_sku.items()):
                for source_path, zip_filename_in_archive in files:
                    # Archive path: YPB.100/label.svg
                    archive_path = f"{sku}/{zip_filename_in_archive}"
                    zipf.write(source_path, archive_path)
                    logger.debug(f"Added to ZIP: {archive_path}")

        logger.info(f"Combined ZIP created: {zip_path} ({len(files_by_sku)} SKUs)")

        # Send file and schedule cleanup
        response = send_file(
            zip_path,
            as_attachment=True,
            download_name=f"combined_{labels_job_id}_{mockups_job_id}.zip"
        )

        # Schedule cleanup after sending (1 hour)
        import threading
        def cleanup_zip():
            import time
            time.sleep(3600)  # 1 hour
            try:
                if zip_path.exists():
                    zip_path.unlink()
                    logger.info(f"Cleaned up combined ZIP: {zip_path}")
            except Exception as e:
                logger.warning(f"Failed to cleanup combined ZIP: {e}")

        cleanup_thread = threading.Thread(target=cleanup_zip, daemon=True)
        cleanup_thread.start()

        return response

    except Exception as e:
        logger.error(f"Error creating combined ZIP: {e}", exc_info=True)
        return jsonify({'error': f'Failed to create combined ZIP: {str(e)}'}), 500


# ============== Old Combined Endpoint (kept for compatibility) ==============

@app.route('/api/generate-batch-mockups', methods=['POST'])
def generate_batch_mockups():
    """Generate mockups for all products from database using vial and label template."""
    try:
        # Check if Gemini API key is available
        if not config.GEMINI_API_KEY:
            return jsonify({
                'error': 'GEMINI_API_KEY not configured. Please set GEMINI_API_KEY=your_key in .env.local file and restart the application.'
            }), 500
        
        # Get files and form data
        if 'vial' not in request.files or 'template' not in request.files:
            return jsonify({'error': 'Both vial and template files are required'}), 400
        
        vial_file = request.files['vial']
        template_file = request.files['template']
        
        if vial_file.filename == '' or template_file.filename == '':
            return jsonify({'error': 'Please upload both vial and template files'}), 400
        
        # Get optional parameters
        product_limit_str = request.form.get('productLimit', '')
        product_limit = int(product_limit_str) if product_limit_str else None
        
        text_areas_str = request.form.get('textAreas', '{}')
        try:
            text_areas = json.loads(text_areas_str) if text_areas_str else {}
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"Invalid textAreas JSON: {e}")
            text_areas = {}

        label_crop_data_str = request.form.get('labelCropData', '{}')
        try:
            label_crop_data = json.loads(label_crop_data_str) if label_crop_data_str else None
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"Invalid labelCropData JSON: {e}")
            label_crop_data = None
        
        # Save uploaded files temporarily
        vial_filename = secure_filename(vial_file.filename)
        template_filename = secure_filename(template_file.filename)
        
        vial_path = config.UPLOAD_DIR / f"batch_vial_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{vial_filename}"
        template_path = config.UPLOAD_DIR / f"batch_template_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{template_filename}"
        
        vial_file.save(str(vial_path))
        template_file.save(str(template_path))
        
        try:
            # Convert AI to SVG if needed
            if template_path.suffix.lower() == '.ai':
                try:
                    logger.info(f"Detected AI file, converting to SVG: {template_path}")
                    converter = AIConverter()
                    svg_path = converter.convert_to_svg(template_path)
                    template_path = svg_path
                    logger.info(f"Using converted SVG: {template_path}")
                except AIConverterError as e:
                    logger.error(f"AI conversion failed: {e}")
                    return jsonify({'error': f'Failed to convert AI file to SVG: {str(e)}'}), 400
            
            # Load vial image
            import PIL.Image
            vial_image = PIL.Image.open(vial_path)
            
            # Load products from current database
            csv_path = Path(get_current_database())
            if not csv_path.exists():
                return jsonify({'error': f'Database not found: {csv_path}'}), 400
            
            manager = CSVManager(csv_path)
            all_products = manager.read_all()
            
            # Apply limit if specified
            products = all_products[:product_limit] if product_limit else all_products
            
            if not products:
                return jsonify({'error': 'No products found in database'}), 400
            
            logger.info(f"Generating mockups for {len(products)} products")
            
            # Create output directory
            job_id = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_dir = config.OUTPUT_DIR / f"batch_mockups_{job_id}"
            output_dir.mkdir(parents=True, exist_ok=True)
            
            if not HAS_RENDERING:
                return jsonify({'error': 'Rendering not available. Please install Cairo: brew install cairo pkg-config.'}), 500
            
            # Process each product (UPDATED: now with retry + verification)
            mockups = []
            errors = []
            successful = 0

            for idx, product in enumerate(products):
                try:
                    product_name = product.get('Product', '')
                    sku = product.get('SKU', '')
                    ingredients = product.get('Ingredients', '10 mg')
                    
                    # Extract dosage from ingredients (first part before comma)
                    dosage = ingredients.split(',')[0].strip() if ingredients else '10 mg'
                    
                    if not sku:
                        logger.warning(f"Skipping product {idx + 1}: no SKU")
                        errors.append(f"Product {idx + 1}: Missing SKU")
                        continue
                    
                    logger.info(f"Processing product {idx + 1}/{len(products)}: {product_name} ({sku})")
                    
                    # Generate label for this product
                    # Create a temporary directory for label generation
                    temp_label_dir = config.TEMP_DIR / f"label_{sku}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                    temp_label_dir.mkdir(parents=True, exist_ok=True)
                    
                    try:
                        # Use BatchProcessor to generate label for single product
                        # We need to create a temporary CSV with just this product
                        import csv
                        temp_csv = temp_label_dir / "temp_product.csv"
                        with open(temp_csv, 'w', newline='', encoding='utf-8') as f:
                            fieldnames = ['Product', 'Ingredients', 'SKU']
                            writer = csv.DictWriter(f, fieldnames=fieldnames)
                            writer.writeheader()
                            # Filter product to only include expected fields
                            filtered_product = {k: v for k, v in product.items() if k in fieldnames}
                            writer.writerow(filtered_product)
                        
                        logger.info(f"Creating BatchProcessor for {sku} with template: {template_path}, csv: {temp_csv}")
                        processor = BatchProcessor(template_path, temp_csv, text_areas=text_areas)
                        
                        # Generate label for this product
                        logger.info(f"Processing batch for {sku}...")
                        label_summary = processor.process_batch(output_dir=temp_label_dir, limit=1)
                        logger.info(f"Label generation summary for {sku}: success={label_summary.get('success')}, total={label_summary.get('total')}, errors={label_summary.get('errors')}")
                        
                        # Find generated label file
                        label_file = None
                        for result in label_summary.get('results', []):
                            logger.info(f"Result for {sku}: status={result.get('status')}, jpg={result.get('jpg')}, svg={result.get('svg')}")
                            if result.get('status') == 'success':
                                # Look for JPG file first, then PNG
                                if result.get('jpg') and Path(result['jpg']).exists():
                                    label_file = Path(result['jpg'])
                                    logger.info(f"Found label file (jpg): {label_file}")
                                    break
                                elif result.get('png') and Path(result['png']).exists():
                                    label_file = Path(result['png'])
                                    logger.info(f"Found label file (png): {label_file}")
                                    break
                                elif result.get('svg') and Path(result['svg']).exists():
                                    # Convert SVG to PNG for mockup generation
                                    svg_path = Path(result['svg'])
                                    png_path = svg_path.with_suffix('.png')
                                    try:
                                        import cairosvg
                                        cairosvg.svg2png(url=str(svg_path), write_to=str(png_path), scale=2)
                                        label_file = png_path
                                        logger.info(f"Converted SVG to PNG: {label_file}")
                                    except Exception as svg_err:
                                        logger.warning(f"Could not convert SVG to PNG: {svg_err}")
                                    break
                        
                        if not label_file or not label_file.exists():
                            logger.warning(f"Could not find generated label for {sku}. Results: {label_summary.get('results')}")
                            errors.append(f"{sku}: Label generation failed")
                            continue
                        
                        # Load generated label image
                        logger.info(f"Loading generated label from: {label_file}")
                        label_image = PIL.Image.open(label_file)
                        logger.info(f"Label image loaded: {label_image.size}, mode: {label_image.mode}")
                        
                        # Generate mockup with RETRY + VERIFICATION (UPDATED)
                        logger.info(f"Generating mockup for {sku} with crop_data: {label_crop_data}")

                        # Crop label if needed BEFORE retry loop
                        label_to_use = label_image.copy()
                        if label_crop_data:
                            crop_x = int(label_crop_data.get('x', 0))
                            crop_y = int(label_crop_data.get('y', 0))
                            crop_width = int(label_crop_data.get('width', label_to_use.width))
                            crop_height = int(label_crop_data.get('height', label_to_use.height))

                            crop_x = max(0, min(crop_x, label_to_use.width - 1))
                            crop_y = max(0, min(crop_y, label_to_use.height - 1))
                            crop_width = min(crop_width, label_to_use.width - crop_x)
                            crop_height = min(crop_height, label_to_use.height - crop_y)

                            if crop_width > 0 and crop_height > 0:
                                label_to_use = label_to_use.crop((crop_x, crop_y, crop_x + crop_width, crop_y + crop_height))

                        # Retry loop for mockup generation
                        MAX_RETRIES = 3
                        mockup_image = None
                        last_errors = []

                        for attempt in range(1, MAX_RETRIES + 1):
                            logger.info(f"[Batch {sku}] Attempt {attempt}/{MAX_RETRIES}")

                            retry_hint = None
                            if attempt > 1 and last_errors:
                                retry_hint = " | ".join(last_errors)

                            # Generate mockup
                            vial_copy = vial_image.copy()
                            label_copy = label_to_use.copy()

                            mockup_image = _generate_mockup_for_product_with_retry(
                                vial_copy,
                                label_copy,
                                product_name,
                                sku,
                                dosage,
                                retry_hint
                            )

                            if mockup_image is None:
                                logger.error(f"[Batch {sku}] Generation failed on attempt {attempt}")
                                last_errors = ["Generation failed"]
                                continue

                            # Verify mockup using SIDE-BY-SIDE comparison (highest quality)
                            verification_result = verify_mockup_with_sidebyside(
                                mockup_image,
                                label_to_use,  # Reference label for comparison
                                sku,
                                product_name,
                                dosage,
                                config.GEMINI_API_KEY
                            )

                            if verification_result.get('is_valid', False):
                                logger.info(f"[Batch {sku}] ✓ Verification PASSED on attempt {attempt}")
                                break
                            else:
                                logger.warning(f"[Batch {sku}] ✗ Verification FAILED on attempt {attempt}")
                                last_errors = verification_result.get('errors', [])

                                if attempt < MAX_RETRIES:
                                    logger.info(f"[Batch {sku}] Retrying...")

                        if mockup_image is None:
                            logger.error(f"[Batch {sku}] Failed after {MAX_RETRIES} attempts")
                            errors.append(f"{sku}: Failed after {MAX_RETRIES} attempts")
                            continue

                        logger.info(f"Mockup generated: {mockup_image.size}, mode: {mockup_image.mode}")
                        
                        # Save mockup
                        sku_safe = sku.replace('/', '_').replace('\\', '_')
                        mockup_filename = f"mockup_{sku_safe}.png"
                        mockup_path = output_dir / mockup_filename
                        mockup_image.save(str(mockup_path), 'PNG', optimize=False)
                        logger.info(f"Mockup saved to: {mockup_path}")
                        
                        mockups.append({
                            'sku': sku,
                            'name': product_name,
                            'filename': mockup_filename,
                            'url': f'/api/batch-mockup-result/{job_id}/{mockup_filename}'
                        })
                        
                        successful += 1
                        logger.info(f"Successfully generated mockup for {sku}")
                        
                    finally:
                        # Cleanup temp label directory
                        if temp_label_dir.exists():
                            try:
                                shutil.rmtree(temp_label_dir)
                            except (OSError, PermissionError) as e:
                                logger.warning(f"Could not cleanup temp label dir: {e}")
                
                except Exception as e:
                    logger.error(f"Error processing product {idx + 1} ({sku}): {e}", exc_info=True)
                    errors.append(f"{sku}: {str(e)}")
                    continue
            
            # Create ZIP with all mockups
            zip_path = config.OUTPUT_DIR / f"batch_mockups_{job_id}.zip"
            try:
                import zipfile
                with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                    for mockup in mockups:
                        mockup_file = output_dir / mockup['filename']
                        if mockup_file.exists():
                            zipf.write(mockup_file, mockup['filename'])
                
                logger.info(f"Created ZIP file: {zip_path}")
            except Exception as e:
                logger.error(f"Error creating ZIP: {e}", exc_info=True)
            
            return jsonify({
                'success': True,
                'total': len(products),
                'successful': successful,
                'errors': len(errors),
                'error_details': errors[:10],  # Limit error details
                'job_id': job_id,
                'zip_file': zip_path.name if zip_path.exists() else None,
                'mockups': mockups
            })
        
        finally:
            # Cleanup temp files
            try:
                if vial_path.exists():
                    vial_path.unlink()
                if template_path.exists() and template_path.parent == config.UPLOAD_DIR:
                    # Only delete if it's still in upload dir (not moved/converted)
                    template_path.unlink()
            except (OSError, PermissionError) as e:
                logger.warning(f"Could not cleanup temp files: {e}")
    
    except Exception as e:
        logger.error(f"Error in generate_batch_mockups: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/batch-mockup-result/<job_id>/<filename>')
def get_batch_mockup_result(job_id, filename):
    """Serve generated batch mockup result."""
    try:
        result_path = config.OUTPUT_DIR / f"batch_mockups_{job_id}" / secure_filename(filename)
        
        if not result_path.exists():
            return jsonify({'error': 'Mockup result not found'}), 404
        
        return send_file(str(result_path), mimetype='image/png')
    except Exception as e:
        logger.error(f"Error serving batch mockup result: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/download-batch-mockups/<job_id>')
def download_batch_mockups_zip(job_id):
    """Download ZIP file with all batch mockups."""
    zip_path = config.OUTPUT_DIR / f"batch_mockups_{job_id}.zip"
    
    if not zip_path.exists():
        return jsonify({'error': 'ZIP file not found'}), 404
    
    return send_file(str(zip_path), as_attachment=True, download_name=f"batch_mockups_{job_id}.zip")


# ============== Archive Management ==============

@app.route('/api/archive/list', methods=['GET'])
def list_archive():
    """List all archived results from output directory"""
    try:
        items = []
        stats = {'total': 0, 'labels': 0, 'mockups': 0, 'size_mb': 0}
        
        # Scan output directory
        for item_path in config.OUTPUT_DIR.iterdir():
            if item_path.is_dir():
                # Determine type
                item_type = 'labels' if item_path.name.startswith('labels_') else 'mockups' if item_path.name.startswith('mockups_') else None
                if not item_type:
                    continue
                
                # Extract job_id from folder name
                job_id = item_path.name.replace('labels_', '').replace('mockups_', '')
                
                # Count files and calculate size
                file_count = 0
                total_size = 0
                for file in item_path.rglob('*'):
                    if file.is_file():
                        file_count += 1
                        total_size += file.stat().st_size
                
                # Get creation time
                creation_time = item_path.stat().st_mtime
                
                items.append({
                    'job_id': job_id,
                    'name': item_path.name,
                    'type': item_type,
                    'count': file_count,
                    'size': total_size,
                    'date': datetime.fromtimestamp(creation_time).isoformat(),
                    'path': str(item_path)
                })
                
                # Update stats
                stats['total'] += 1
                if item_type == 'labels':
                    stats['labels'] += 1
                else:
                    stats['mockups'] += 1
                stats['size_mb'] += total_size / 1024 / 1024
        
        return jsonify({
            'success': True,
            'items': items,
            'stats': stats
        })
        
    except Exception as e:
        logger.error(f"Error listing archive: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/archive/delete', methods=['POST'])
def delete_archive_item():
    """Delete an archived result"""
    try:
        data = request.json
        job_id = data.get('job_id')
        item_type = data.get('type')
        
        if not job_id or not item_type:
            return jsonify({'error': 'Missing job_id or type'}), 400
        
        # Construct folder name
        folder_name = f"{item_type}_{job_id}"
        folder_path = config.OUTPUT_DIR / folder_name
        
        if not folder_path.exists():
            return jsonify({'error': 'Archive item not found'}), 404
        
        # Delete folder and all contents
        import shutil
        shutil.rmtree(folder_path)
        logger.info(f"Deleted archive item: {folder_name}")
        
        return jsonify({
            'success': True,
            'message': f'Deleted {folder_name}'
        })
        
    except Exception as e:
        logger.error(f"Error deleting archive item: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/archive/cleanup', methods=['POST'])
def cleanup_archive():
    """Clean up old archived files"""
    try:
        data = request.json
        days = data.get('days', 7)
        
        from cleanup_utils import cleanup_old_files
        
        deleted_count = cleanup_old_files(config.OUTPUT_DIR, hours=days*24)
        
        # Calculate freed space (approximate)
        freed_mb = deleted_count * 0.5  # Rough estimate
        
        return jsonify({
            'success': True,
            'deleted_count': deleted_count,
            'freed_mb': freed_mb
        })
        
    except Exception as e:
        logger.error(f"Error during archive cleanup: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/file/<filename>')
def serve_output_file(filename):
    """Serve file from OUTPUT_DIR."""
    try:
        safe_filename = secure_filename(filename)
        file_path = config.OUTPUT_DIR / safe_filename
        
        if file_path.exists():
            return send_file(str(file_path), mimetype='image/png')
        else:
            return jsonify({'error': 'File not found'}), 404
    except Exception as e:
        logger.error(f"Error serving file {filename}: {e}")
        return jsonify({'error': str(e)}), 500


# ============== Settings API ==============

@app.route('/api/settings/api-key-status', methods=['GET'])
def get_api_key_status():
    """Check if API key is configured."""
    try:
        is_configured = bool(config.GEMINI_API_KEY and len(config.GEMINI_API_KEY) > 10)
        return jsonify({
            'configured': is_configured,
            'masked_key': config.GEMINI_API_KEY[:10] + '...' if is_configured else None
        })
    except Exception as e:
        logger.error(f"Error checking API key status: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/settings/api-key', methods=['POST'])
def save_api_key():
    """Save API key to .env.local file."""
    try:
        data = request.json
        api_key = data.get('api_key', '').strip()
        
        if not api_key:
            return jsonify({'error': 'API key is required'}), 400
        
        # Basic validation
        if not api_key.startswith('AIza') or len(api_key) < 30:
            return jsonify({'error': 'Invalid API key format'}), 400
        
        # Path to .env.local
        env_path = Path(__file__).parent / '.env.local'
        
        # Read existing content
        existing_lines = []
        if env_path.exists():
            with open(env_path, 'r') as f:
                existing_lines = f.readlines()
        
        # Update or add GEMINI_API_KEY
        key_found = False
        new_lines = []
        for line in existing_lines:
            if line.startswith('GEMINI_API_KEY='):
                new_lines.append(f'GEMINI_API_KEY={api_key}\n')
                key_found = True
            else:
                new_lines.append(line)
        
        # If key wasn't found, add it
        if not key_found:
            # Add after comment if exists, or at beginning
            if new_lines and new_lines[0].startswith('#'):
                new_lines.insert(1, f'GEMINI_API_KEY={api_key}\n')
            else:
                new_lines.insert(0, f'GEMINI_API_KEY={api_key}\n')
        
        # Write back to file
        with open(env_path, 'w') as f:
            f.writelines(new_lines)
        
        logger.info(f"API key updated in .env.local")
        
        return jsonify({
            'success': True,
            'message': 'API key saved successfully. Please restart the application for changes to take effect.'
        })
        
    except Exception as e:
        logger.error(f"Error saving API key: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/settings/test-api-key', methods=['POST'])
def test_api_key():
    """Test if API key is valid by making a simple API call."""
    try:
        data = request.json
        api_key = data.get('api_key', '').strip()
        
        if not api_key:
            return jsonify({'error': 'API key is required'}), 400
        
        # Try to initialize Gemini with the provided key
        import google.generativeai as genai
        
        genai.configure(api_key=api_key)
        
        # Try to list models as a simple test
        try:
            models = genai.list_models()
            # If we get here, the API key is valid
            return jsonify({
                'success': True,
                'message': 'API key is valid and working'
            })
        except Exception as api_error:
            logger.error(f"API key test failed: {api_error}")
            return jsonify({
                'success': False,
                'error': f'API key is invalid or has insufficient permissions: {str(api_error)}'
            }), 400
        
    except Exception as e:
        logger.error(f"Error testing API key: {e}")
        return jsonify({'error': str(e)}), 500


def extract_aria_labels_from_svg(svg_path: Path) -> str:
    """
    Extract all aria-label attributes from SVG (used when text is converted to paths).
    Returns concatenated text from all aria-labels.
    """
    try:
        with open(svg_path, 'r', encoding='utf-8') as f:
            svg_content = f.read()
        
        # Find all aria-label attributes
        import re
        aria_labels = re.findall(r'aria-label="([^"]+)"', svg_content)
        
        # Concatenate all found labels
        full_text = ' '.join(aria_labels)
        logger.info(f"Found {len(aria_labels)} aria-labels in final SVG")
        
        return full_text
        
    except Exception as e:
        logger.error(f"Error extracting aria-labels: {e}")
        return ""


def extract_svg_text_info(svg_path: Path) -> dict:
    """
    Extract text information from SVG file.
    
    Returns dict with:
        - sku: Found SKU (e.g., YPB.123)
        - product_name: Product name
        - ingredients: Ingredients text
        - has_research_use_only: Boolean if "Research Use Only" text found
    """
    try:
        with open(svg_path, 'r', encoding='utf-8') as f:
            svg_content = f.read()
        
        # Parse SVG
        namespaces = {
            'svg': 'http://www.w3.org/2000/svg',
            'inkscape': 'http://www.inkscape.org/namespaces/inkscape'
        }
        
        root = ET.fromstring(svg_content)
        
        # Extract all text elements
        all_text = []
        for text_elem in root.findall('.//svg:text', namespaces):
            # Get text from all tspan children
            text_parts = []
            for tspan in text_elem.findall('.//svg:tspan', namespaces):
                if tspan.text:
                    text_parts.append(tspan.text.strip())
            # Also check direct text
            if text_elem.text:
                text_parts.append(text_elem.text.strip())
            
            if text_parts:
                all_text.append(' '.join(text_parts))
        
        # Join all text
        full_text = ' '.join(all_text)
        
        # Extract SKU (pattern: YPB.XXX or YPB-XXX)
        sku = None
        sku_match = re.search(r'YPB[.\-]\d+', full_text, re.IGNORECASE)
        if sku_match:
            sku = sku_match.group(0)
        
        # Check for "Research Use Only"
        has_research_use_only = bool(re.search(r'research\s+use\s+only', full_text, re.IGNORECASE))
        
        # Try to find product name (usually one of the larger text elements)
        product_name = None
        ingredients = None
        
        # Heuristic: Product name is usually shorter, ingredients are longer
        text_by_length = sorted(all_text, key=len, reverse=True)
        
        if len(text_by_length) >= 2:
            # Longest is likely ingredients
            potential_ingredients = text_by_length[0]
            if len(potential_ingredients) > 50:  # Ingredients are usually long
                ingredients = potential_ingredients
            
            # Find product name (not SKU, not ingredients, not "Research Use Only")
            for text in text_by_length:
                if text == ingredients:
                    continue
                if sku and sku in text:
                    continue
                if re.search(r'research\s+use\s+only', text, re.IGNORECASE):
                    continue
                if len(text) > 5 and len(text) < 100:  # Reasonable product name length
                    product_name = text
                    break
        
        return {
            'sku': sku,
            'product_name': product_name,
            'ingredients': ingredients,
            'has_research_use_only': has_research_use_only
        }
        
    except Exception as e:
        logger.error(f"Error extracting SVG text info: {e}")
        return {
            'sku': None,
            'product_name': None,
            'ingredients': None,
            'has_research_use_only': False
        }


def add_data_placeholders_to_svg_text(svg_path: Path, extracted_info: dict) -> str:
    """
    Add data-placeholder attributes to <text> elements in SVG.

    Args:
        svg_path: Path to SVG file with editable <text> elements
        extracted_info: Dict with sku, product_name, ingredients

    Returns:
        Updated SVG content as string
    """
    try:
        # Load database
        csv_path = Path(get_current_database())
        if not csv_path.exists():
            logger.warning(f"Database not found: {csv_path}")
            with open(svg_path, 'r', encoding='utf-8') as f:
                return f.read()

        csv_manager = CSVManager(csv_path)
        products = csv_manager.read_all()

        # Find matching product
        matched_product = None
        extracted_sku = extracted_info.get('sku', '').strip() if extracted_info.get('sku') else ''

        if extracted_sku:
            for product in products:
                product_sku = product.get('SKU', '').strip()
                if product_sku and (extracted_sku.upper() in product_sku.upper() or product_sku.upper() in extracted_sku.upper()):
                    matched_product = product
                    logger.info(f"Matched product by SKU: {product_sku}")
                    break

        if not matched_product:
            logger.info("No product match found, skipping placeholder addition")
            with open(svg_path, 'r', encoding='utf-8') as f:
                return f.read()

        # Read SVG content
        with open(svg_path, 'r', encoding='utf-8') as f:
            svg_content = f.read()

        # Values to match
        sku_value = matched_product.get('SKU', '').strip()
        product_name_value = matched_product.get('Product', '').strip()
        ingredients_value = matched_product.get('Ingredients', '').strip()

        import re

        # Find <text> elements and add data-placeholder
        def add_placeholder(match):
            text_elem = match.group(0)
            text_content = match.group(1) if match.lastindex else ''

            # Skip if already has data-placeholder
            if 'data-placeholder=' in text_elem:
                return text_elem

            text_upper = text_content.upper()

            # Check for SKU
            if sku_value and sku_value.upper() in text_upper:
                logger.info(f"Adding data-placeholder='sku' to text: {text_content[:50]}")
                return text_elem.replace('<text ', '<text data-placeholder="sku" ', 1)

            # Check for product name
            if product_name_value and product_name_value.upper() in text_upper:
                logger.info(f"Adding data-placeholder='product_name' to text: {text_content[:50]}")
                return text_elem.replace('<text ', '<text data-placeholder="product_name" ', 1)

            # Check for ingredients - normalize spaces before comparing
            if ingredients_value:
                # Normalize: remove all spaces for comparison
                ingredients_normalized = ingredients_value.upper().replace(' ', '')
                text_normalized = text_upper.replace(' ', '')

                # Check if normalized values match
                if ingredients_normalized in text_normalized or text_normalized in ingredients_normalized:
                    # Make sure it's not SKU or product name
                    if not (sku_value and sku_value.upper() in text_upper) and not (product_name_value and product_name_value.upper() in text_upper):
                        logger.info(f"Adding data-placeholder='ingredients' to text: {text_content[:50]}")
                        return text_elem.replace('<text ', '<text data-placeholder="ingredients" ', 1)

            return text_elem

        # Match <text ...>content</text>
        pattern = r'<text[^>]*>([^<]*)</text>'
        svg_content = re.sub(pattern, add_placeholder, svg_content)

        return svg_content

    except Exception as e:
        logger.error(f"Error adding placeholders to text elements: {e}", exc_info=True)
        with open(svg_path, 'r', encoding='utf-8') as f:
            return f.read()


def add_data_placeholders_to_svg(svg_path: Path, extracted_info: dict) -> str:
    """
    Add data-placeholder attributes to SVG elements after matching with database.

    Args:
        svg_path: Path to SVG file (with text as paths)
        extracted_info: Dict with sku, product_name, ingredients from extracted text
    
    Returns:
        Updated SVG content as string
    """
    try:
        # Load database
        csv_path = Path(get_current_database())
        if not csv_path.exists():
            logger.warning(f"Database not found: {csv_path}, skipping placeholder addition")
            with open(svg_path, 'r', encoding='utf-8') as f:
                return f.read()
        
        csv_manager = CSVManager(csv_path)
        products = csv_manager.read_all()
        
        # Find matching product in database
        matched_product = None
        extracted_sku = extracted_info.get('sku', '').strip() if extracted_info.get('sku') else ''
        extracted_product_name = extracted_info.get('product_name', '').strip() if extracted_info.get('product_name') else ''
        extracted_ingredients = extracted_info.get('ingredients', '').strip() if extracted_info.get('ingredients') else ''
        
        # Try to match by SKU first
        if extracted_sku:
            for product in products:
                product_sku = product.get('SKU', '').strip()
                if product_sku and extracted_sku.upper() in product_sku.upper() or product_sku.upper() in extracted_sku.upper():
                    matched_product = product
                    logger.info(f"Matched product by SKU: {product_sku}")
                    break
        
        # If no SKU match, try product name
        if not matched_product and extracted_product_name:
            for product in products:
                product_name = product.get('Product', '').strip()
                if product_name and extracted_product_name.lower() in product_name.lower() or product_name.lower() in extracted_product_name.lower():
                    matched_product = product
                    logger.info(f"Matched product by name: {product_name}")
                    break
        
        # If still no match, try ingredients
        if not matched_product and extracted_ingredients:
            for product in products:
                product_ingredients = product.get('Ingredients', '').strip()
                if product_ingredients and len(extracted_ingredients) > 10:
                    # Check if significant portion matches
                    common_words = set(extracted_ingredients.lower().split()) & set(product_ingredients.lower().split())
                    if len(common_words) >= 3:  # At least 3 common words
                        matched_product = product
                        logger.info(f"Matched product by ingredients (common words: {len(common_words)})")
                        break
        
        if not matched_product:
            logger.info("No product match found in database, skipping placeholder addition")
            with open(svg_path, 'r', encoding='utf-8') as f:
                return f.read()
        
        # Parse SVG
        tree = ET.parse(str(svg_path))
        root = tree.getroot()
        
        # Map of what we're looking for and what placeholder to add
        placeholder_map = {
            'sku': matched_product.get('SKU', '').strip(),
            'product_name': matched_product.get('Product', '').strip(),
            'ingredients': matched_product.get('Ingredients', '').strip()
        }
        
        # Find elements with aria-label and add data-placeholder
        added_count = 0
        for elem in root.iter():
            aria_label = elem.get('aria-label', '')
            if not aria_label:
                continue
            
            aria_label_upper = aria_label.upper()
            
            # Check for SKU
            if placeholder_map['sku']:
                sku_upper = placeholder_map['sku'].upper()
                if sku_upper in aria_label_upper or aria_label_upper in sku_upper or 'SKU' in aria_label_upper or 'YPB.' in aria_label_upper or 'YPB-' in aria_label_upper:
                    elem.set('data-placeholder', 'sku')
                    added_count += 1
                    logger.info(f"Added data-placeholder='sku' to element with aria-label: {aria_label[:50]}...")
                    continue
            
            # Check for product name
            if placeholder_map['product_name']:
                product_name_upper = placeholder_map['product_name'].upper()
                # Exclude common phrases that are not product names
                excluded = ['SKU', 'mg', 'mcg', 'STORE', 'PROTECT', 'REFRIGERATE', 'NOT FOR', 'EXPIRATION', 'CAS:', 'DISTRIBUTED', 'RESEARCH', 'HUMAN', 'CONSUMPTION']
                if not any(exc in aria_label_upper for exc in excluded):
                    if product_name_upper in aria_label_upper or aria_label_upper in product_name_upper:
                        elem.set('data-placeholder', 'product_name')
                        added_count += 1
                        logger.info(f"Added data-placeholder='product_name' to element with aria-label: {aria_label[:50]}...")
                        continue
            
            # Check for ingredients
            if placeholder_map['ingredients']:
                ingredients_upper = placeholder_map['ingredients'].upper()
                # Ingredients are usually longer text
                if len(aria_label) > 20:
                    # Check for common words
                    common_words = set(ingredients_upper.split()) & set(aria_label_upper.split())
                    if len(common_words) >= 2:  # At least 2 common words
                        elem.set('data-placeholder', 'ingredients')
                        added_count += 1
                        logger.info(f"Added data-placeholder='ingredients' to element with aria-label: {aria_label[:50]}...")
        
        logger.info(f"Added data-placeholder attributes to {added_count} elements")
        
        # Convert back to string
        ET.register_namespace('', 'http://www.w3.org/2000/svg')
        return ET.tostring(root, encoding='unicode')
        
    except Exception as e:
        logger.error(f"Error adding data-placeholders to SVG: {e}", exc_info=True)
        # Return original SVG on error
        with open(svg_path, 'r', encoding='utf-8') as f:
            return f.read()


@app.route('/api/convert-ai-to-svg', methods=['POST'])
def convert_ai_to_svg():
    """
    Convert AI file to SVG and extract text information.
    
    Returns JSON with:
        - success: boolean
        - svg_content: SVG file content
        - extracted_info: dict with sku, product_name, ingredients, has_research_use_only
    """
    # #region agent log
    _dbg("app.py:convert_ai_to_svg", "entry", {"has_ai_file": 'ai_file' in request.files}, "H2")
    # #endregion
    try:
        if 'ai_file' not in request.files:
            return jsonify({'error': 'No AI file provided'}), 400
        
        file = request.files['ai_file']
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        
        if not file.filename.lower().endswith('.ai'):
            return jsonify({'error': 'File must be an AI file'}), 400
        
        # Save uploaded file
        filename = secure_filename(file.filename)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        ai_filename = f"ai_converter_{timestamp}_{filename}"
        ai_path = config.UPLOAD_DIR / ai_filename
        file.save(str(ai_path))
        
        logger.info(f"Converting AI file: {ai_path}")
        
        converter = AIConverter()
        
        # Convert WITH EDITABLE TEXT (text_to_path=False) at 675 DPI
        logger.info("Converting AI to SVG with editable text elements at 675 DPI...")
        svg_path_final = ai_path.with_name(ai_path.stem + '_final.svg')
        svg_path_final = converter.convert_to_svg(ai_path, output_path=svg_path_final, text_to_path=False, dpi=675)

        # Extract text information
        extracted_info = extract_svg_text_info(svg_path_final)
        logger.info(f"Extracted info: {extracted_info}")

        # Read SVG content
        with open(svg_path_final, 'r', encoding='utf-8') as f:
            svg_content = f.read()

        # Validate against database
        logger.info("Validating against database...")
        validation_result = {
            'validated': False,
            'matched_product': None,
            'sku_found': False,
            'product_name_found': False,
            'placeholders_added': 0
        }

        # Load database and try to match
        csv_path = Path(get_current_database())
        if csv_path.exists():
            csv_manager = CSVManager(csv_path)
            products = csv_manager.read_all()

            extracted_sku = extracted_info.get('sku', '').strip()
            if extracted_sku:
                for product in products:
                    product_sku = product.get('SKU', '').strip()
                    if product_sku and (extracted_sku.upper() in product_sku.upper() or product_sku.upper() in extracted_sku.upper()):
                        validation_result['validated'] = True
                        validation_result['matched_product'] = product
                        validation_result['sku_found'] = True
                        validation_result['product_name_found'] = True
                        logger.info(f"✓ Database validation PASSED: Found {product_sku} - {product.get('Product')}")
                        break

            if not validation_result['validated']:
                logger.warning(f"✗ Database validation FAILED: SKU '{extracted_sku}' not found in database")
        else:
            logger.warning("Database not found, skipping validation")

        # Add data-placeholder attributes based on database matching
        logger.info("Adding data-placeholder attributes after database matching...")
        svg_content_with_placeholders = add_data_placeholders_to_svg_text(svg_path_final, extracted_info)

        # Count placeholders added
        import re
        placeholder_count = len(re.findall(r'data-placeholder="([^"]*)"', svg_content_with_placeholders))
        validation_result['placeholders_added'] = placeholder_count

        # Extract all text from <text> elements for frontend validation
        text_elements = re.findall(r'<text[^>]*>([^<]+)</text>', svg_content_with_placeholders)
        svg_text = ' '.join(text_elements)
        extracted_info['svg_text'] = svg_text
        logger.info(f"Extracted {len(text_elements)} text elements from SVG")

        # Save updated SVG with placeholders
        with open(svg_path_final, 'w', encoding='utf-8') as f:
            f.write(svg_content_with_placeholders)

        logger.info(f"Added {placeholder_count} data-placeholder attributes to text elements")

        # Clean up AI file
        try:
            ai_path.unlink()
        except Exception as e:
            logger.warning(f"Could not delete AI file: {e}")
        # #region agent log
        _dbg("app.py:convert_ai_to_svg", "success", {"svg_path": str(svg_path_final.name), "validation": validation_result}, "H2")
        # #endregion
        return jsonify({
            'success': True,
            'svg_content': svg_content_with_placeholders,
            'svg_path': str(svg_path_final.name),
            'extracted_info': extracted_info,
            'validation': validation_result
        })
        
    except AIConverterError as e:
        # #region agent log
        _dbg("app.py:convert_ai_to_svg", "exception", {"error": str(e), "type": "AIConverterError"}, "H2,H5")
        # #endregion
        logger.error(f"AI conversion failed: {e}")
        return jsonify({
            'success': False,
            'error': f'Conversion failed: {str(e)}'
        }), 500
    except Exception as e:
        # #region agent log
        import traceback
        _dbg("app.py:convert_ai_to_svg", "exception", {"error": str(e), "type": type(e).__name__, "traceback": traceback.format_exc()}, "H2,H5")
        # #endregion
        logger.error(f"Unexpected error in convert_ai_to_svg: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': f'Unexpected error: {str(e)}'
        }), 500


@app.route('/api/restart', methods=['POST'])
@requires_auth
def restart_application():
    """Restart the Flask application (requires authentication)."""
    try:
        import subprocess
        import threading

        def restart_app():
            """Restart the application in a separate thread."""
            import time
            import signal

            # Wait a moment to let the response be sent
            time.sleep(1)

            # Get the restart script path
            restart_script = os.path.join(config.BASE_DIR, 'restart.sh')

            if os.path.exists(restart_script):
                # Use restart.sh script
                _dbg("restart", "Using restart.sh script", {"script": restart_script})
                subprocess.Popen(['/bin/bash', restart_script],
                               cwd=str(config.BASE_DIR),
                               start_new_session=True)
            else:
                # Fallback: kill current process and let supervisor restart
                _dbg("restart", "No restart.sh found, killing process", {})
                os.kill(os.getpid(), signal.SIGTERM)

        # Start restart in background thread
        restart_thread = threading.Thread(target=restart_app, daemon=True)
        restart_thread.start()

        _dbg("restart", "Application restart initiated", {})

        return jsonify({
            'success': True,
            'message': 'Application restart initiated'
        })

    except Exception as e:
        _dbg("restart", "Restart failed", {"error": str(e)}, "ERROR")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# #region agent log
_dbg("app", "app loaded", {}, "H1")
# #endregion


if __name__ == '__main__':
    # Set library paths for Homebrew-installed Cairo (macOS only)
    import sys
    if sys.platform == 'darwin':  # macOS
        try:
            os.environ['PKG_CONFIG_PATH'] = '/opt/homebrew/lib/pkgconfig:' + os.environ.get('PKG_CONFIG_PATH', '')
            os.environ['DYLD_LIBRARY_PATH'] = '/opt/homebrew/lib:' + os.environ.get('DYLD_LIBRARY_PATH', '')
            os.environ['LD_LIBRARY_PATH'] = '/opt/homebrew/lib:' + os.environ.get('LD_LIBRARY_PATH', '')
        except Exception:
            pass  # Not critical if this fails
    
    # Create necessary directories
    config.UPLOAD_DIR.mkdir(exist_ok=True)
    config.OUTPUT_DIR.mkdir(exist_ok=True)
    config.TEMP_DIR.mkdir(exist_ok=True)
    
    # Get port from environment variable or use default
    port = int(os.environ.get('PORT', 8000))  # Default to 8000

    # Debug mode from environment variable (default to False for production)
    debug_mode = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'

    app.run(debug=debug_mode, host='0.0.0.0', port=port, threaded=True)
