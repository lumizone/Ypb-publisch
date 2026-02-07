"""Text formatter for intelligent text formatting in SVG.

INTELIGENTNE FORMATOWANIE OPARTE NA WYMIARACH OBSZARU:

Algorytm:
1. Oblicz tekst przy oryginalnej czcionce
2. Dla każdej możliwej liczby linii (1-6), oblicz:
   - Optymalny rozmiar czcionki aby tekst wypełnił szerokość
   - Wymaganą wysokość dla tych linii
3. Wybierz kombinację która:
   - Mieści się w obszarze
   - Ma NAJWIĘKSZY możliwy rozmiar czcionki (najlepsza czytelność)
   - Preferuje mniej linii przy podobnym rozmiarze

ZASADA: Tekst ma być jak NAJWIĘKSZY, nie jak najmniejszy!
"""

import re
from math import ceil
from typing import Dict, Tuple, List, Optional
from PIL import Image, ImageDraw, ImageFont
import logging

logger = logging.getLogger(__name__)


class TextFormatterError(Exception):
    """Raised when text formatting fails."""
    pass


class TextFormatter:
    """Intelligently formats text for SVG - optimizes for MAXIMUM readability."""

    # Minimum font sizes (for readability)
    MIN_FONT_SIZE_PX = 8.0
    MIN_FONT_SIZE_INGREDIENTS_PX = 10.0
    MIN_FONT_SIZE_PRODUCT_NAME_PX = 12.0

    # Absolute minimum (emergency fallback)
    ABSOLUTE_MIN_FONT_SIZE = 6.0

    # Maximum font sizes (to prevent too large text)
    MAX_FONT_SIZE_PX = 72.0

    # Line height multiplier (1.2 = 20% extra space between lines)
    LINE_HEIGHT_MULTIPLIER = 1.20

    # Maximum lines to try
    MAX_LINES = 6

    # Shared draw context for text measurement (avoids creating 42,000 temp images)
    _measure_img = None
    _measure_draw = None

    def __init__(self):
        self.font_cache = {}
        self._pil_font_cache = {}
        self._font_path_cache = {}  # Cache: font_family → resolved file path
        self._text_width_cache = {}  # Cache: (text, font_family, font_size) → width

    def _map_font_name(self, font_family: str) -> List[str]:
        """Map common font names to their actual filenames across different font packages.

        Returns list of possible filenames to try (in priority order).
        """
        # Normalize input
        font_lower = font_family.lower().strip()

        # Font name mapping (common names → actual filenames)
        # Priority: Microsoft Core Fonts > Liberation > DejaVu > Fallbacks
        font_map = {
            # ARIAL family (Microsoft Core Fonts - EXACT match!)
            'arial': ['arial.ttf', 'Arial.ttf', 'LiberationSans-Regular.ttf', 'DejaVuSans.ttf'],
            'arial bold': ['arialbd.ttf', 'Arial-Bold.ttf', 'LiberationSans-Bold.ttf', 'DejaVuSans-Bold.ttf'],
            'arial italic': ['ariali.ttf', 'Arial-Italic.ttf', 'LiberationSans-Italic.ttf', 'DejaVuSans-Oblique.ttf'],
            'arial bold italic': ['arialbi.ttf', 'Arial-BoldItalic.ttf', 'LiberationSans-BoldItalic.ttf', 'DejaVuSans-BoldOblique.ttf'],
            'arial black': ['ariblk.ttf', 'Arial-Black.ttf', 'DejaVuSans-ExtraBold.ttf'],

            # TIMES NEW ROMAN family
            'times new roman': ['times.ttf', 'Times-Roman.ttf', 'LiberationSerif-Regular.ttf', 'DejaVuSerif.ttf'],
            'times new roman bold': ['timesbd.ttf', 'Times-Bold.ttf', 'LiberationSerif-Bold.ttf', 'DejaVuSerif-Bold.ttf'],
            'times new roman italic': ['timesi.ttf', 'Times-Italic.ttf', 'LiberationSerif-Italic.ttf', 'DejaVuSerif-Italic.ttf'],
            'times new roman bold italic': ['timesbi.ttf', 'Times-BoldItalic.ttf', 'LiberationSerif-BoldItalic.ttf', 'DejaVuSerif-BoldItalic.ttf'],

            # COURIER NEW family
            'courier new': ['cour.ttf', 'Courier-New.ttf', 'LiberationMono-Regular.ttf', 'DejaVuSansMono.ttf'],
            'courier new bold': ['courbd.ttf', 'Courier-Bold.ttf', 'LiberationMono-Bold.ttf', 'DejaVuSansMono-Bold.ttf'],
            'courier new italic': ['couri.ttf', 'Courier-Italic.ttf', 'LiberationMono-Italic.ttf', 'DejaVuSansMono-Oblique.ttf'],
            'courier new bold italic': ['courbi.ttf', 'Courier-BoldItalic.ttf', 'LiberationMono-BoldItalic.ttf', 'DejaVuSansMono-BoldOblique.ttf'],

            # VERDANA family
            'verdana': ['verdana.ttf', 'Verdana.ttf', 'DejaVuSans.ttf'],
            'verdana bold': ['verdanab.ttf', 'Verdana-Bold.ttf', 'DejaVuSans-Bold.ttf'],
            'verdana italic': ['verdanai.ttf', 'Verdana-Italic.ttf', 'DejaVuSans-Oblique.ttf'],
            'verdana bold italic': ['verdanaz.ttf', 'Verdana-BoldItalic.ttf', 'DejaVuSans-BoldOblique.ttf'],

            # GEORGIA family
            'georgia': ['georgia.ttf', 'Georgia.ttf', 'DejaVuSerif.ttf'],
            'georgia bold': ['georgiab.ttf', 'Georgia-Bold.ttf', 'DejaVuSerif-Bold.ttf'],
            'georgia italic': ['georgiai.ttf', 'Georgia-Italic.ttf', 'DejaVuSerif-Italic.ttf'],
            'georgia bold italic': ['georgiaz.ttf', 'Georgia-BoldItalic.ttf', 'DejaVuSerif-BoldItalic.ttf'],

            # TREBUCHET MS family
            'trebuchet ms': ['trebuc.ttf', 'Trebuchet-MS.ttf', 'DejaVuSans.ttf'],
            'trebuchet ms bold': ['trebucbd.ttf', 'Trebuchet-MS-Bold.ttf', 'DejaVuSans-Bold.ttf'],
            'trebuchet ms italic': ['trebucit.ttf', 'Trebuchet-MS-Italic.ttf', 'DejaVuSans-Oblique.ttf'],
            'trebuchet ms bold italic': ['trebucbi.ttf', 'Trebuchet-MS-BoldItalic.ttf', 'DejaVuSans-BoldOblique.ttf'],

            # HELVETICA family (macOS)
            'helvetica': ['Helvetica.ttf', 'LiberationSans-Regular.ttf', 'DejaVuSans.ttf'],
            'helvetica bold': ['Helvetica-Bold.ttf', 'LiberationSans-Bold.ttf', 'DejaVuSans-Bold.ttf'],
            'helvetica oblique': ['Helvetica-Oblique.ttf', 'LiberationSans-Italic.ttf', 'DejaVuSans-Oblique.ttf'],

            # CALIBRI family (Microsoft Office - not in Core Fonts, fallback to Liberation)
            'calibri': ['calibri.ttf', 'Calibri.ttf', 'LiberationSans-Regular.ttf'],
            'calibri bold': ['calibrib.ttf', 'Calibri-Bold.ttf', 'LiberationSans-Bold.ttf'],
            'calibri italic': ['calibrii.ttf', 'Calibri-Italic.ttf', 'LiberationSans-Italic.ttf'],
            'calibri bold italic': ['calibriz.ttf', 'Calibri-BoldItalic.ttf', 'LiberationSans-BoldItalic.ttf'],

            # ACUMIN VARIABLE CONCEPT (Adobe Font → Google Fonts alternatives)
            'acuminvariableconcept': ['Inter-Regular.ttf', 'Montserrat-Regular.ttf', 'SourceSansPro-Regular.ttf', 'LiberationSans-Regular.ttf'],
            'acumin variable concept': ['Inter-Regular.ttf', 'Montserrat-Regular.ttf', 'SourceSansPro-Regular.ttf', 'LiberationSans-Regular.ttf'],
            'acumin': ['Inter-Regular.ttf', 'Montserrat-Regular.ttf', 'SourceSansPro-Regular.ttf', 'LiberationSans-Regular.ttf'],

            # GOTHAM (Hoefler & Co. → Montserrat is best free alternative)
            'gotham': ['Montserrat-Medium.ttf', 'Montserrat-Regular.ttf', 'NunitoSans-Regular.ttf', 'Arial.ttf', 'LiberationSans-Regular.ttf'],
            'gotham medium': ['Montserrat-Medium.ttf', 'Montserrat-SemiBold.ttf', 'NunitoSans-SemiBold.ttf', 'Arial-Bold.ttf', 'LiberationSans-Bold.ttf'],
            'gotham bold': ['Montserrat-Bold.ttf', 'Montserrat-SemiBold.ttf', 'NunitoSans-Bold.ttf', 'Arial-Bold.ttf', 'LiberationSans-Bold.ttf'],
            'gothammedium': ['Montserrat-Medium.ttf', 'Montserrat-SemiBold.ttf', 'NunitoSans-SemiBold.ttf', 'Arial-Bold.ttf', 'LiberationSans-Bold.ttf'],

            # MONTSERRAT (Google Font - Gotham alternative)
            'montserrat': ['Montserrat-Regular.ttf', 'LiberationSans-Regular.ttf'],
            'montserrat medium': ['Montserrat-Medium.ttf', 'Montserrat-SemiBold.ttf', 'LiberationSans-Bold.ttf'],
            'montserrat bold': ['Montserrat-Bold.ttf', 'LiberationSans-Bold.ttf'],
            'montserrat semibold': ['Montserrat-SemiBold.ttf', 'Montserrat-Medium.ttf', 'LiberationSans-Bold.ttf'],

            # INTER (Google Font - Acumin alternative)
            'inter': ['Inter-Regular.ttf', 'LiberationSans-Regular.ttf'],
            'inter medium': ['Inter-Medium.ttf', 'Inter-SemiBold.ttf', 'LiberationSans-Bold.ttf'],
            'inter bold': ['Inter-Bold.ttf', 'LiberationSans-Bold.ttf'],

            # ROBOTO (Google Font - very popular)
            'roboto': ['Roboto-Regular.ttf', 'LiberationSans-Regular.ttf'],
            'roboto medium': ['Roboto-Medium.ttf', 'Roboto-Bold.ttf', 'LiberationSans-Bold.ttf'],
            'roboto bold': ['Roboto-Bold.ttf', 'LiberationSans-Bold.ttf'],

            # OPEN SANS (Google Font - very popular)
            'open sans': ['OpenSans-Regular.ttf', 'LiberationSans-Regular.ttf'],
            'open sans medium': ['OpenSans-Medium.ttf', 'OpenSans-SemiBold.ttf', 'LiberationSans-Bold.ttf'],
            'open sans bold': ['OpenSans-Bold.ttf', 'LiberationSans-Bold.ttf'],
        }

        # Try exact match first
        if font_lower in font_map:
            candidates = font_map[font_lower]
        else:
            # Fallback: try the original name + common extensions
            base_name = font_family.replace(' ', '-')
            candidates = [
                f"{font_family}.ttf",
                f"{base_name}.ttf",
                f"{font_family.replace(' ', '')}.ttf",
                # Generic fallback
                'LiberationSans-Regular.ttf',
                'DejaVuSans.ttf',
                'FreeSans.ttf'
            ]

        return candidates

    def _get_pil_font(self, font_family: str, font_size: float) -> ImageFont.FreeTypeFont:
        """Get PIL font object, with caching and intelligent font name mapping."""
        font_key = (font_family, int(font_size))
        if font_key in self._pil_font_cache:
            return self._pil_font_cache[font_key]

        font = None

        # Font directories to search (priority order)
        font_directories = [
            # Microsoft Core Fonts (BEST - exact match!)
            "/usr/share/fonts/truetype/msttcorefonts",
            # macOS paths
            "/System/Library/Fonts/Supplemental",
            "/Library/Fonts",
            "/System/Library/Fonts",
            # Linux paths (Liberation, DejaVu, etc.)
            "/usr/share/fonts/truetype/liberation",
            "/usr/share/fonts/truetype/liberation2",
            "/usr/share/fonts/truetype/dejavu",
            "/usr/share/fonts/truetype/freefont",
            "~/.fonts",
            # Windows paths
            "C:/Windows/Fonts",
        ]

        # FAST PATH: Use cached font path if we already resolved this font family
        font_family_lower = font_family.lower().strip()
        if font_family_lower in self._font_path_cache:
            cached_path = self._font_path_cache[font_family_lower]
            try:
                font = ImageFont.truetype(cached_path, int(font_size))
                self._pil_font_cache[font_key] = font
                return font
            except (OSError, IOError):
                # Cached path no longer valid, clear and re-resolve
                del self._font_path_cache[font_family_lower]

        # SLOW PATH: First time - resolve font path by scanning directories
        # Get list of possible font filenames (handles "Arial Bold" → "arialbd.ttf" mapping)
        font_candidates = self._map_font_name(font_family)

        # Try all combinations: directory × font_candidate
        for font_filename in font_candidates:
            for directory in font_directories:
                path = f"{directory}/{font_filename}"
                try:
                    font = ImageFont.truetype(path, int(font_size))
                    # CACHE the resolved path for future calls (different sizes)
                    self._font_path_cache[font_family_lower] = path
                    logger.info(f"✓ Resolved font: '{font_family}' → {font_filename} from {directory}")
                    break
                except (OSError, IOError):
                    continue
            if font:
                break

        # Fallback fonts (try common fonts if specific font not found)
        if font is None:
            fallback_fonts = [
                # Microsoft Core Fonts (BEST!)
                'arial.ttf',
                'times.ttf',
                'verdana.ttf',
                # Liberation fonts (metrically compatible with MS fonts)
                'LiberationSans-Regular.ttf',
                'LiberationSerif-Regular.ttf',
                # DejaVu fonts (comprehensive)
                'DejaVuSans.ttf',
                'DejaVuSerif.ttf',
                # FreeFonts
                'FreeSans.ttf',
                'FreeSerif.ttf',
                # macOS
                'Arial.ttf',
                'Helvetica.ttf',
            ]
            for fallback_name in fallback_fonts:
                for directory in font_directories:
                    fallback_path = f"{directory}/{fallback_name}"
                    try:
                        font = ImageFont.truetype(fallback_path, int(font_size))
                        # Cache fallback path too
                        self._font_path_cache[font_family_lower] = fallback_path
                        logger.warning(f"⚠ Resolved fallback: '{font_family}' → {fallback_name} (from {directory})")
                        break
                    except (OSError, IOError):
                        continue
                if font:
                    break

        if font is None:
            # Last resort: use default font
            try:
                font = ImageFont.load_default()
            except Exception as e:
                # Even default font failed
                print(f"Warning: Could not load default font: {e}")
                font = None

        self._pil_font_cache[font_key] = font
        return font

    def measure_text_width(self, text: str, font_family: str, font_size: float) -> float:
        """
        Measure text width using PIL/Pillow.

        Args:
            text: Text to measure
            font_family: Font family name (e.g., 'Arial', 'Arial-BoldMT')
            font_size: Font size in pixels

        Returns:
            Text width in pixels
        """
        if not text:
            return 0.0

        # Check cache first
        cache_key = (text, font_family, int(font_size))
        if cache_key in self._text_width_cache:
            return self._text_width_cache[cache_key]

        try:
            font = self._get_pil_font(font_family, font_size)

            if font is None:
                # Fallback estimate
                return len(text) * font_size * 0.55

            # Reuse shared draw context (avoids creating temp images)
            if TextFormatter._measure_img is None:
                TextFormatter._measure_img = Image.new('RGB', (2000, 500), color='white')
                TextFormatter._measure_draw = ImageDraw.Draw(TextFormatter._measure_img)

            bbox = TextFormatter._measure_draw.textbbox((0, 0), text, font=font)
            width = float(bbox[2] - bbox[0])

            self._text_width_cache[cache_key] = width
            return width

        except Exception as e:
            logger.warning(f"Error measuring text width: {e}, using estimate")
            # Fallback: estimate width based on character count
            return len(text) * font_size * 0.55

    def measure_text_height(self, text: str, font_family: str, font_size: float) -> float:
        """Measure text height for a single line."""
        try:
            font = self._get_pil_font(font_family, font_size)
            if font is None:
                return font_size * 1.2

            # Reuse shared draw context
            if TextFormatter._measure_img is None:
                TextFormatter._measure_img = Image.new('RGB', (2000, 500), color='white')
                TextFormatter._measure_draw = ImageDraw.Draw(TextFormatter._measure_img)

            bbox = TextFormatter._measure_draw.textbbox((0, 0), text or "Ay", font=font)
            height = bbox[3] - bbox[1]
            return float(height)
        except Exception as e:
            # Fallback: approximate line height as 1.2x font size
            logger.warning(f"Could not measure line height: {e}")
            return font_size * 1.2

    def extract_font_size(self, style: str) -> float:
        """Extract font size from style string."""
        if not style:
            return 12.0

        # Try px first
        match = re.search(r'font-size:\s*([\d.]+)px', style)
        if match:
            return float(match.group(1))

        # Try pt
        match = re.search(r'font-size:\s*([\d.]+)pt', style)
        if match:
            return float(match.group(1)) * 1.333  # pt to px

        return 12.0

    def extract_font_family(self, style: str) -> str:
        """Extract font family from style string."""
        if not style:
            return 'Arial'

        # Try to extract font-family
        pattern = r"font-family:\s*['\"]?([^;'\"]+)['\"]?"
        match = re.search(pattern, style)
        if match:
            font_family = match.group(1).strip().strip("'\"")
            # Take first font in list
            font_family = font_family.split(',')[0].strip()
            return font_family

        return 'Arial'

    def _tokenize_text(self, text: str, placeholder_name: str = None) -> List[str]:
        """
        Tokenize text for line distribution.

        For ingredients: split by "/" and spaces, keeping "/" as separator.
        For others: split by spaces.
        """
        if not text:
            return []

        if placeholder_name == 'ingredients' and '/' in text:
            # Split by "/" and keep "/" as breakpoint
            parts = []
            for segment in text.split('/'):
                segment = segment.strip()
                if segment:
                    words = segment.split()
                    parts.extend(words)
                    parts.append('/')  # Add separator as token
            # Remove trailing separator
            if parts and parts[-1] == '/':
                parts.pop()
            return parts
        else:
            return text.split()

    def _greedy_wrap(self, tokens: List[str], max_width: float,
                     font_family: str, font_size: float) -> List[str]:
        """
        Greedy text wrapping - fit as many words as possible per line.

        This is more accurate than even distribution because it uses
        actual measured widths.
        """
        if not tokens:
            return []

        lines = []
        current_line = []
        current_width = 0
        space_width = self.measure_text_width(' ', font_family, font_size)

        for token in tokens:
            token_width = self.measure_text_width(token, font_family, font_size)

            # Check if token fits on current line
            new_width = current_width + (space_width if current_line else 0) + token_width

            if new_width <= max_width or not current_line:
                # Add to current line
                current_line.append(token)
                current_width = new_width
            else:
                # Start new line
                if current_line:
                    lines.append(' '.join(current_line))
                current_line = [token]
                current_width = token_width

        # Don't forget the last line
        if current_line:
            lines.append(' '.join(current_line))

        return lines

    def _balanced_wrap(self, tokens: List[str], num_lines: int,
                       max_width: float, font_family: str, font_size: float) -> List[str]:
        """
        Balanced text wrapping - distribute tokens to minimize raggedness.

        For ingredients with "/" separators, tries to split at separators
        and distribute items evenly (e.g., 2:2 instead of 1:3 for 4 items).
        """
        if not tokens:
            return []

        n = len(tokens)
        if n <= num_lines:
            # Each token gets its own line
            return [t for t in tokens if t != '/']

        # Check if this is ingredients with "/" separators
        has_separators = '/' in tokens

        if has_separators:
            # Split into ingredient groups (between "/" separators)
            groups = []
            current_group = []

            for token in tokens:
                if token == '/':
                    if current_group:
                        groups.append(current_group)
                        current_group = []
                else:
                    current_group.append(token)
            if current_group:
                groups.append(current_group)

            num_groups = len(groups)

            # Try to distribute groups evenly across lines
            # ALWAYS use even distribution for ingredients - font size will be adjusted later
            if num_groups > 0 and num_groups >= num_lines:
                # Calculate how many groups per line for even distribution
                base_groups_per_line = num_groups // num_lines
                extra_groups = num_groups % num_lines

                lines = []
                group_idx = 0

                for line_num in range(num_lines):
                    # Determine how many groups for this line
                    groups_for_this_line = base_groups_per_line
                    if line_num < extra_groups:
                        groups_for_this_line += 1

                    # Get groups for this line
                    line_groups = groups[group_idx:group_idx + groups_for_this_line]
                    group_idx += groups_for_this_line

                    if line_groups:
                        # Build line text
                        line_text = ' / '.join([' '.join(g) for g in line_groups])
                        lines.append(line_text)
                        # DON'T check width here - let _find_optimal_font_size handle it
                        # This ensures even distribution (2:2) over width-based (1:3)

                # Return balanced lines - font size adjustment happens in caller
                if len(lines) == num_lines and group_idx == num_groups:
                    logger.info(f"Balanced wrap: {num_groups} groups into {num_lines} lines = {[len(l.split(' / ')) for l in lines]} distribution")
                    return lines

        # Fallback to original algorithm for non-ingredients or if above didn't work
        space_width = self.measure_text_width(' ', font_family, font_size)
        token_widths = [self.measure_text_width(t, font_family, font_size) for t in tokens]

        # Calculate prefix widths (cumulative)
        prefix_widths = [0]
        for i, (token, width) in enumerate(zip(tokens, token_widths)):
            if i == 0:
                prefix_widths.append(width)
            else:
                prefix_widths.append(prefix_widths[-1] + space_width + width)

        def line_width(i, j):
            """Width of tokens[i:j+1] on single line."""
            if i > j:
                return 0
            return prefix_widths[j + 1] - prefix_widths[i] - (space_width if i > 0 else 0)

        # Try to distribute evenly by width
        total_width = prefix_widths[-1]
        target_width_per_line = total_width / num_lines

        lines = []
        current_start = 0

        for line_num in range(num_lines):
            if line_num == num_lines - 1:
                # Last line gets everything remaining
                line_tokens = tokens[current_start:]
            else:
                # Find best break point
                best_end = current_start
                best_diff = float('inf')

                for end in range(current_start, n):
                    width = line_width(current_start, end)
                    if width > max_width and end > current_start:
                        break
                    diff = abs(width - target_width_per_line)
                    if diff < best_diff:
                        best_diff = diff
                        best_end = end

                line_tokens = tokens[current_start:best_end + 1]
                current_start = best_end + 1

            if line_tokens:
                # Clean up separators at line boundaries
                line_text = ' '.join(t for t in line_tokens if t)
                # Fix spacing around "/" - ensure " / " format
                line_text = re.sub(r'\s*/\s*', ' / ', line_text)  # Normalize to " / "
                line_text = line_text.strip(' /')
                if line_text:
                    lines.append(line_text)

        return lines

    def _find_optimal_font_size(self, lines: List[str], max_width: float, max_height: float,
                                 font_family: str, min_size: float, max_size: float) -> float:
        """
        Find the largest font size that makes ALL lines fit within constraints.

        Uses binary search for efficiency.
        """
        if not lines:
            return max_size

        # Quick check - does max_size fit?
        if self._layout_fits(lines, max_width, max_height, font_family, max_size):
            return max_size

        # Quick check - does min_size fit?
        if not self._layout_fits(lines, max_width, max_height, font_family, min_size):
            return min_size * 0.8  # Even minimum doesn't fit

        # Binary search
        low, high = min_size, max_size

        for _ in range(15):  # 15 iterations gives good precision
            mid = (low + high) / 2

            if self._layout_fits(lines, max_width, max_height, font_family, mid):
                low = mid  # Can go bigger
            else:
                high = mid  # Need to go smaller

        # Return slightly smaller to ensure fit
        return low * 0.97

    def _layout_fits(self, lines: List[str], max_width: float, max_height: float,
                     font_family: str, font_size: float) -> bool:
        """Check if layout fits within constraints."""
        # Check width
        for line in lines:
            if self.measure_text_width(line, font_family, font_size) > max_width:
                return False

        # Check height
        line_height = font_size * self.LINE_HEIGHT_MULTIPLIER
        total_height = line_height * len(lines)

        return total_height <= max_height

    def find_optimal_layout(self, text: str, max_width: float, max_height: float,
                            font_family: str, original_font_size: float,
                            placeholder_name: str = None) -> Dict:
        """
        Find the OPTIMAL layout for text - PRESERVING original size if it fits.

        IMPORTANT: If the original font size fits, use it without changes!
        Only reduce size if the text doesn't fit at original size.

        Strategy:
        1. FIRST: Check if original font size fits - if yes, use it!
        2. Only if original doesn't fit, try different numbers of lines
        3. Find the largest font size that fits
        4. Choose the combination with LARGEST font size
        """
        # Determine minimum font size based on placeholder type
        if placeholder_name == 'product_name':
            min_font_size = self.MIN_FONT_SIZE_PRODUCT_NAME_PX
        elif placeholder_name == 'ingredients':
            min_font_size = self.MIN_FONT_SIZE_INGREDIENTS_PX
        else:
            min_font_size = self.MIN_FONT_SIZE_PX

        # Tokenize text
        tokens = self._tokenize_text(text, placeholder_name)

        if not tokens:
            return {
                'lines': [text] if text else [''],
                'font_size': original_font_size,
                'line_height': original_font_size * self.LINE_HEIGHT_MULTIPLIER,
                'num_lines': 1
            }

        # If no height constraint, use a large default
        if max_height is None or max_height <= 0:
            max_height = 500.0
        if max_width is None or max_width <= 0:
            max_width = 500.0

        # ========== STEP 1: CHECK IF ORIGINAL SIZE FITS ==========
        # This is the KEY fix - only change size if necessary!

        # Try single line with original font size
        single_line_width = self.measure_text_width(text, font_family, original_font_size)
        single_line_height = original_font_size * self.LINE_HEIGHT_MULTIPLIER

        if single_line_width <= max_width and single_line_height <= max_height:
            # ORIGINAL SIZE FITS! No changes needed.
            logger.info(f"ORIGINAL SIZE FITS for '{text[:30]}...': {original_font_size:.1f}px, single line")
            return {
                'lines': [text],
                'font_size': original_font_size,
                'line_height': single_line_height,
                'num_lines': 1
            }

        # Try wrapping at original font size
        # For ingredients (has "/"), ONLY try optimal line count at original size
        # If doesn't fit, fall through to STEP 2 which reduces font size
        has_separators = '/' in text
        if has_separators:
            # Count ingredient groups (separated by "/")
            num_groups = text.count('/') + 1

            # Calculate optimal number of lines for even distribution
            # 4 ingredients → 2 lines (2:2), 6 ingredients → 2 lines (3:3), etc.
            optimal_lines = min(num_groups // 2 + (1 if num_groups % 2 else 0), self.MAX_LINES)
            optimal_lines = max(2, optimal_lines)  # Minimum 2 lines

            # Try ONLY the optimal line count at original size
            wrapped_lines = self._balanced_wrap(tokens, optimal_lines, max_width, font_family, original_font_size)
            if wrapped_lines and self._layout_fits(wrapped_lines, max_width, max_height, font_family, original_font_size):
                logger.info(f"ORIGINAL SIZE FITS with balanced {optimal_lines} lines for '{text[:30]}...': {original_font_size:.1f}px")
                return {
                    'lines': wrapped_lines,
                    'font_size': original_font_size,
                    'line_height': original_font_size * self.LINE_HEIGHT_MULTIPLIER,
                    'num_lines': len(wrapped_lines)
                }
            # If doesn't fit at original size, fall through to STEP 2 to reduce font
        else:
            # For non-ingredients, use greedy wrap
            wrapped_lines = self._greedy_wrap(tokens, max_width, font_family, original_font_size)
            if wrapped_lines and self._layout_fits(wrapped_lines, max_width, max_height, font_family, original_font_size):
                logger.info(f"ORIGINAL SIZE FITS with wrap for '{text[:30]}...': {original_font_size:.1f}px, {len(wrapped_lines)} lines")
                return {
                    'lines': wrapped_lines,
                    'font_size': original_font_size,
                    'line_height': original_font_size * self.LINE_HEIGHT_MULTIPLIER,
                    'num_lines': len(wrapped_lines)
                }

        # ========== STEP 2: ORIGINAL DOESN'T FIT - FIND OPTIMAL ==========
        logger.info(f"Original size {original_font_size:.1f}px doesn't fit for '{text[:30]}...', searching for optimal")

        best_layout = None
        best_font_size = 0

        # Maximum font size to try (don't go above original)
        max_possible_font = original_font_size

        # Try 1 to MAX_LINES lines
        for num_lines in range(1, self.MAX_LINES + 1):
            # Skip if we don't have enough tokens
            if len([t for t in tokens if t != '/']) < num_lines and num_lines > 1:
                continue

            # Use balanced wrapping for this number of lines
            lines = self._balanced_wrap(tokens, num_lines, max_width, font_family, original_font_size)

            if not lines:
                continue

            # Find optimal font size for these lines
            font_size = self._find_optimal_font_size(
                lines, max_width, max_height, font_family,
                self.ABSOLUTE_MIN_FONT_SIZE, max_possible_font
            )

            if font_size < self.ABSOLUTE_MIN_FONT_SIZE:
                continue

            # Verify fit
            if not self._layout_fits(lines, max_width, max_height, font_family, font_size):
                # For ingredients (has /), keep balanced distribution, try more lines
                # DON'T fall back to greedy wrap which creates uneven 1:3 distribution
                has_separators = '/' in tokens
                if has_separators:
                    # Continue to next iteration (more lines, smaller font, but balanced)
                    continue
                # For non-ingredients, try greedy wrap as fallback
                lines = self._greedy_wrap(tokens, max_width, font_family, font_size)
                if not lines or not self._layout_fits(lines, max_width, max_height, font_family, font_size):
                    continue

            # This layout works! Check if it's better than previous
            is_better = False
            if best_layout is None:
                is_better = True
            elif font_size > best_font_size * 1.05:  # Significantly larger font
                is_better = True
            elif len(lines) < best_layout['num_lines'] and font_size >= best_font_size * 0.85:
                # FEWER LINES is STRONGLY preferred (even with smaller font)
                # For ingredients, 2 lines at 18px is better than 3 lines at 20px
                is_better = True
            elif font_size >= best_font_size * 0.95 and len(lines) <= best_layout['num_lines']:
                # Similar font size, same or fewer lines
                is_better = True

            if is_better:
                best_font_size = font_size
                best_layout = {
                    'lines': lines,
                    'font_size': font_size,
                    'line_height': font_size * self.LINE_HEIGHT_MULTIPLIER,
                    'num_lines': len(lines)
                }

        # Fallback: force fit with more lines and smaller font
        # CRITICAL: Text MUST fit within the area - this is a HARD limit
        if best_layout is None:
            logger.warning(f"Could not find optimal layout for '{text[:30]}...', using aggressive fallback")

            # Start with minimum font and keep reducing until it fits
            test_font = min_font_size
            lines = self._greedy_wrap(tokens, max_width, font_family, test_font)

            if not lines:
                lines = [text]

            # Reduce font until it ACTUALLY fits - no minimum limit here!
            # The text area constraint is more important than minimum font size
            for _ in range(100):  # More iterations to ensure fit
                if self._layout_fits(lines, max_width, max_height, font_family, test_font):
                    break
                test_font *= 0.85  # Reduce more aggressively
                lines = self._greedy_wrap(tokens, max_width, font_family, test_font)
                # NO minimum check - we MUST fit within the area
                if test_font < 1.0:  # Absolute floor to prevent infinite loop
                    test_font = 1.0
                    # If still doesn't fit, truncate text
                    if not self._layout_fits(lines, max_width, max_height, font_family, test_font):
                        logger.error(f"Text cannot fit even at 1px, truncating: '{text[:30]}...'")
                        # Truncate each line to fit
                        truncated_lines = []
                        for line in lines:
                            while self.measure_text_width(line, font_family, test_font) > max_width and len(line) > 3:
                                line = line[:-4] + "..."
                            truncated_lines.append(line)
                        lines = truncated_lines
                    break

            best_layout = {
                'lines': lines,
                'font_size': test_font,
                'line_height': test_font * self.LINE_HEIGHT_MULTIPLIER,
                'num_lines': len(lines)
            }

        if best_layout['font_size'] < original_font_size:
            logger.info(f"REDUCED SIZE for '{text[:30]}...': {original_font_size:.1f}px -> {best_layout['font_size']:.1f}px, {best_layout['num_lines']} lines")
        else:
            logger.info(f"Layout for '{text[:30]}...': {best_layout['num_lines']} lines, font_size={best_layout['font_size']:.1f}px")

        return best_layout

    def format_text(self, text: str, placeholder_info: Dict, max_width: Optional[float] = None,
                    max_height: Optional[float] = None, placeholder_name: Optional[str] = None) -> Dict:
        """
        INTELLIGENT TEXT FORMATTING - Optimizes for MAXIMUM READABILITY.

        Core algorithm:
        1. Try different numbers of lines (1 to MAX_LINES)
        2. For each, find the LARGEST font size that fits
        3. Choose the combination with the BIGGEST font (most readable)

        Args:
            text: Text to format
            placeholder_info: Dictionary with placeholder information (style, font-size, etc.)
            max_width: Maximum width constraint
            max_height: Maximum height constraint (important for optimal layout!)
            placeholder_name: Name of placeholder ('ingredients', 'product_name', etc.)

        Returns:
            Dictionary with:
            - 'text': Original text
            - 'lines': List of text lines
            - 'font_size': Optimal font size (LARGEST that fits)
            - 'needs_wrap': Whether text is multi-line
            - 'font_family': Font family used
            - 'line_height': Line height in pixels
        """
        style = placeholder_info.get('style', '')
        font_family = self.extract_font_family(style)
        original_font_size = self.extract_font_size(style)

        # Also check for direct font-size in placeholder_info (from template parser)
        # ALWAYS use direct font-size if provided - it takes precedence over style
        direct_font_size = placeholder_info.get('font-size', '')
        if direct_font_size:
            # Try to parse direct font-size
            try:
                if isinstance(direct_font_size, (int, float)):
                    original_font_size = float(direct_font_size)
                elif isinstance(direct_font_size, str):
                    size_match = re.match(r'([\d.]+)', direct_font_size)
                    if size_match:
                        original_font_size = float(size_match.group(1))
            except (ValueError, TypeError) as e:
                # Could not parse font size, keep default
                print(f"Warning: Could not parse font size '{direct_font_size}': {e}")

        logger.info(f"format_text: text='{text[:40]}...', style='{style[:60] if style else 'EMPTY'}', "
                   f"original_font_size={original_font_size:.1f}px, max_width={max_width}, max_height={max_height}")

        # Set defaults if not provided
        if max_width is None:
            max_width = 200.0
        if max_height is None:
            max_height = 100.0

        # Use the optimal layout finder
        layout = self.find_optimal_layout(
            text=text,
            max_width=max_width,
            max_height=max_height,
            font_family=font_family,
            original_font_size=original_font_size,
            placeholder_name=placeholder_name
        )

        return {
            'text': text,
            'lines': layout['lines'],
            'font_size': layout['font_size'],
            'needs_wrap': len(layout['lines']) > 1,
            'font_family': font_family,
            'line_height': layout.get('line_height', layout['font_size'] * self.LINE_HEIGHT_MULTIPLIER)
        }

    def smart_wrap_text(self, text: str, max_width: float, font_family: str, font_size: float,
                        placeholder_name: str = None, max_lines: int = 6) -> List[str]:
        """
        Wrap text into optimal number of lines based on available width.

        This is a simplified wrapper - the main logic is in find_optimal_layout().
        """
        tokens = self._tokenize_text(text, placeholder_name)

        # Try to fit in single line first
        single_line_width = self.measure_text_width(text, font_family, font_size)
        if single_line_width <= max_width:
            return [text]

        # Use greedy wrap
        return self._greedy_wrap(tokens, max_width, font_family, font_size)
