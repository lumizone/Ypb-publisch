"""AI to SVG converter using PyMuPDF - with EDITABLE TEXT at 675 DPI"""

from pathlib import Path
from typing import Optional, List, Dict, Any
import logging
import re
import html

logger = logging.getLogger(__name__)

DEFAULT_EXPORT_DPI = 675


class AIConverterError(Exception):
    """Raised when AI conversion fails."""
    pass


class AIConverter:
    """Converts Adobe Illustrator (.ai) files to SVG using PyMuPDF."""

    def __init__(self):
        self.pymupdf_available = self._check_pymupdf()
        if not self.pymupdf_available:
            logger.warning("PyMuPDF not found. Install: pip install PyMuPDF")

    def _check_pymupdf(self) -> bool:
        """Check if PyMuPDF is available."""
        try:
            import fitz
            logger.info(f"PyMuPDF version: {fitz.version}")
            return True
        except ImportError:
            return False

    def convert_to_svg(
        self,
        ai_path: Path,
        output_path: Optional[Path] = None,
        text_to_path: bool = False,
        dpi: int = DEFAULT_EXPORT_DPI
    ) -> Path:
        """
        Convert AI to SVG with editable text @ specified DPI.

        Args:
            ai_path: Path to .ai file
            output_path: Output path (default: same as input with .svg)
            text_to_path: False = editable <text> (default), True = paths
            dpi: Target DPI (default: 675)

        Returns:
            Path to output SVG
        """
        if not self.pymupdf_available:
            raise AIConverterError("PyMuPDF not installed")

        ai_path = Path(ai_path)

        if not ai_path.exists():
            raise AIConverterError(f"File not found: {ai_path}")

        if ai_path.suffix.lower() not in ['.ai', '.pdf']:
            raise AIConverterError(f"Not an AI/PDF file: {ai_path}")

        if output_path is None:
            output_path = ai_path.with_suffix('.svg')
        else:
            output_path = Path(output_path)

        output_path.parent.mkdir(parents=True, exist_ok=True)

        logger.info(f"Converting: {ai_path} -> {output_path}")
        logger.info(f"Settings: DPI={dpi}, text_to_path={text_to_path}")

        try:
            import fitz

            # Open AI file
            doc = fitz.open(str(ai_path))

            if len(doc) == 0:
                doc.close()
                raise AIConverterError("AI file has no pages")

            page = doc[0]

            # Get original dimensions (in points, 72 DPI)
            rect = page.rect
            width_pt = rect.width
            height_pt = rect.height

            # Calculate scale factor for target DPI
            scale = dpi / 72.0

            # Final dimensions in pixels at target DPI
            width_px = width_pt * scale
            height_px = height_pt * scale

            logger.info(f"Original: {width_pt:.1f} x {height_pt:.1f} pt (72 DPI)")
            logger.info(f"Output: {width_px:.1f} x {height_px:.1f} px ({dpi} DPI)")
            logger.info(f"Scale factor: {scale:.4f}")

            if text_to_path:
                # Text as paths mode - but add aria-label for text identification
                svg_content = page.get_svg_image()
                svg_content = self._apply_scale_to_svg(svg_content, scale)
                # Add aria-label attributes to text groups
                svg_content = self._add_aria_labels_to_text_paths(svg_content)
            else:
                # Extract text data BEFORE generating SVG
                text_data = self._extract_text_data(page)
                logger.info(f"Extracted {len(text_data)} text spans")

                # Generate SVG with graphics only (text as paths for positioning reference)
                svg_content = page.get_svg_image()

                # Remove the text paths from SVG (we'll add real <text> elements)
                svg_content = self._remove_text_paths(svg_content)

                # Apply scale to SVG dimensions
                svg_content = self._apply_scale_to_svg(svg_content, scale)

                # Add editable text elements
                svg_content = self._add_text_elements(svg_content, text_data, scale)

            doc.close()

            # Write output
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(svg_content)

            # Verify result
            self._verify_svg(output_path)

            logger.info(f"SUCCESS: {output_path}")
            return output_path

        except Exception as e:
            if isinstance(e, AIConverterError):
                raise
            raise AIConverterError(f"Conversion failed: {e}")

    def _add_aria_labels_to_text_paths(self, svg_content: str) -> str:
        """
        Add aria-label attributes to SVG by grouping <use data-text="X"> elements.

        PyMuPDF generates <use data-text="S"> for each character. We group these
        by vertical position (same line) and create aria-label with combined text.
        """
        import re

        try:
            # Find all <use data-text="X" ...> elements using regex (more robust than XML parsing)
            use_pattern = r'<use\s+data-text="([^"])"[^>]*transform="matrix\([^,]+,[^,]+,[^,]+,[^,]+,([^,]+),([^)]+)\)"[^>]*/>'
            matches = list(re.finditer(use_pattern, svg_content))

            if not matches:
                # Try alternative pattern (attributes in different order)
                use_pattern = r'<use[^>]*data-text="([^"])"[^>]*transform="[^"]*matrix\([^,]+,[^,]+,[^,]+,[^,]+,([^,]+),([^)]+)\)"[^>]*/>'
                matches = list(re.finditer(use_pattern, svg_content))

            if not matches:
                logger.info("No <use data-text> elements found for aria-label")
                return svg_content

            # Extract character info
            use_elements = []
            for match in matches:
                char = match.group(1)
                x_pos = float(match.group(2))
                y_pos = float(match.group(3))
                use_elements.append({
                    'match': match,
                    'char': char,
                    'x': x_pos,
                    'y': y_pos,
                    'start': match.start(),
                    'end': match.end(),
                    'text': match.group(0)
                })

            # Sort by Y position (lines) then X position (characters in line)
            use_elements.sort(key=lambda e: (round(e['y'], 1), e['x']))

            # Group by Y position (same line = same Y within tolerance)
            lines = []
            current_line = []
            current_y = None
            y_tolerance = 0.5  # Tighter tolerance for same line

            for elem in use_elements:
                if current_y is None or abs(elem['y'] - current_y) <= y_tolerance:
                    current_line.append(elem)
                    current_y = elem['y'] if current_y is None else current_y
                else:
                    if current_line:
                        lines.append(current_line)
                    current_line = [elem]
                    current_y = elem['y']

            if current_line:
                lines.append(current_line)

            logger.info(f"Found {len(lines)} text lines from {len(use_elements)} characters")

            # Add aria-label to first element of each line
            replacements = []
            for line in lines:
                line.sort(key=lambda e: e['x'])
                text = ''.join(e['char'] for e in line).strip()
                if text and len(text) > 1:
                    first_elem = line[0]
                    # Add aria-label attribute to the first <use> element
                    old_text = first_elem['text']
                    # Insert aria-label after <use
                    new_text = old_text.replace('<use ', f'<use aria-label="{text}" ', 1)
                    replacements.append((old_text, new_text))
                    logger.debug(f"Added aria-label: '{text[:50]}...'")

            # Apply replacements
            result = svg_content
            for old, new in replacements:
                result = result.replace(old, new, 1)

            logger.info(f"Added aria-labels to {len(replacements)} text groups")
            return result

        except Exception as e:
            logger.warning(f"Failed to add aria-labels: {e}")
            return svg_content

    def _extract_text_data(self, page) -> List[Dict[str, Any]]:
        """Extract text with positions, fonts, sizes, colors from page."""
        import fitz
        text_data = []

        # Get detailed text info
        text_dict = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)

        for block in text_dict.get("blocks", []):
            if block.get("type") != 0:  # 0 = text block
                continue

            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    text = span.get("text", "").strip()
                    if not text:
                        continue

                    # Get position (origin is bottom-left of text baseline)
                    bbox = span.get("bbox", [0, 0, 0, 0])
                    origin = span.get("origin", (bbox[0], bbox[3]))

                    # Get font info
                    font = span.get("font", "Arial")
                    size = span.get("size", 12)

                    # Get color (as integer, convert to hex)
                    color_int = span.get("color", 0)
                    color_hex = self._int_to_hex_color(color_int)

                    # Font flags
                    flags = span.get("flags", 0)
                    is_bold = bool(flags & 2**4)  # bit 4 = bold
                    is_italic = bool(flags & 2**1)  # bit 1 = italic

                    text_data.append({
                        "text": text,
                        "x": origin[0],
                        "y": origin[1],
                        "font": font,
                        "size": size,
                        "color": color_hex,
                        "bold": is_bold,
                        "italic": is_italic,
                        "bbox": bbox
                    })

        return text_data

    def _int_to_hex_color(self, color_int: int) -> str:
        """Convert integer color to hex string."""
        if color_int == 0:
            return "#000000"

        # PyMuPDF returns color as integer in RGB format
        r = (color_int >> 16) & 0xFF
        g = (color_int >> 8) & 0xFF
        b = color_int & 0xFF

        return f"#{r:02x}{g:02x}{b:02x}"

    def _remove_text_paths(self, svg: str) -> str:
        """Remove text path elements from SVG (we'll add real <text> later)."""
        # PyMuPDF generates <use data-text="X" xlink:href="#font_..."> for text glyphs
        # We need to remove these and keep only graphics

        # Count before removal for logging
        use_count_before = svg.count('<use ')

        # Remove <use> elements with data-text attribute (these are text glyphs)
        svg = re.sub(r'<use\s+data-text="[^"]*"[^>]*/>', '', svg)

        # Also remove font symbol definitions (id="font_...")
        svg = re.sub(r'<symbol\s+id="font_[^"]*"[^>]*>.*?</symbol>', '', svg, flags=re.DOTALL)

        # Remove any remaining glyph <use> elements (backup pattern)
        svg = re.sub(r'<use[^>]*xlink:href="#font_[^"]*"[^>]*/>', '', svg)
        svg = re.sub(r'<use[^>]*xlink:href="#g[0-9]+"[^>]*/>', '', svg)

        use_count_after = svg.count('<use ')
        logger.info(f"Removed {use_count_before - use_count_after} text glyph <use> elements")

        return svg

    def _apply_scale_to_svg(self, svg: str, scale: float) -> str:
        """Apply scale factor to SVG dimensions and wrap content."""

        # Extract current dimensions
        width_match = re.search(r'<svg[^>]*\swidth="([0-9.]+)"', svg)
        height_match = re.search(r'<svg[^>]*\sheight="([0-9.]+)"', svg)

        if not width_match or not height_match:
            logger.warning("Could not find SVG dimensions")
            return svg

        old_width = float(width_match.group(1))
        old_height = float(height_match.group(1))

        new_width = old_width * scale
        new_height = old_height * scale

        # Update width
        svg = re.sub(
            r'(<svg[^>]*\swidth=")[0-9.]+(")',
            f'\\g<1>{new_width:.2f}\\g<2>',
            svg
        )

        # Update height
        svg = re.sub(
            r'(<svg[^>]*\sheight=")[0-9.]+(")',
            f'\\g<1>{new_height:.2f}\\g<2>',
            svg
        )

        # Update or add viewBox
        viewbox = f"0 0 {new_width:.2f} {new_height:.2f}"
        if 'viewBox=' in svg:
            svg = re.sub(
                r'(<svg[^>]*\sviewBox=")[^"]+(")',
                f'\\g<1>{viewbox}\\g<2>',
                svg
            )
        else:
            svg = re.sub(
                r'(<svg\s)',
                f'\\g<1>viewBox="{viewbox}" ',
                svg
            )

        # Wrap all content in a scale group
        match = re.search(r'(<svg[^>]*>)(.*)(</svg>)', svg, re.DOTALL)
        if match:
            svg_open = match.group(1)
            content = match.group(2)
            svg_close = match.group(3)

            svg = f'{svg_open}\n<g transform="scale({scale})">\n{content}\n</g>\n{svg_close}'

        return svg

    def _add_text_elements(self, svg: str, text_data: List[Dict], scale: float) -> str:
        """Add editable <text> elements to SVG."""
        if not text_data:
            logger.warning("No text data to add")
            return svg

        text_elements = []

        for item in text_data:
            text = html.escape(item["text"])

            # Scale coordinates
            x = item["x"] * scale
            y = item["y"] * scale
            size = item["size"] * scale

            # Build font style
            font_family = self._clean_font_name(item["font"])
            font_weight = "bold" if item["bold"] else "normal"
            font_style = "italic" if item["italic"] else "normal"

            # Create text element with aria-label for text extraction
            elem = (
                f'<text x="{x:.2f}" y="{y:.2f}" '
                f'aria-label="{text}" '
                f'font-family="{font_family}, Arial, sans-serif" '
                f'font-size="{size:.2f}px" '
                f'font-weight="{font_weight}" '
                f'font-style="{font_style}" '
                f'fill="{item["color"]}">'
                f'{text}</text>'
            )
            text_elements.append(elem)

        # Insert text block before </svg>
        text_block = '\n<!-- EDITABLE TEXT - Generated at {} DPI -->\n'.format(int(scale * 72))
        text_block += '<g id="editable-text">\n'
        text_block += '\n'.join(text_elements)
        text_block += '\n</g>\n'

        svg = svg.replace('</svg>', text_block + '</svg>')

        logger.info(f"Added {len(text_elements)} editable text elements")
        return svg

    def _clean_font_name(self, font: str) -> str:
        """Clean up font name for CSS."""
        # Remove common suffixes
        font = re.sub(r'-(Bold|Italic|Regular|Medium|Light|Book|Black|Heavy).*$', '', font, flags=re.IGNORECASE)
        font = re.sub(r'MT$|PS$', '', font)

        # Common font mappings
        font_map = {
            'ArialMT': 'Arial',
            'Helvetica': 'Helvetica',
            'HelveticaNeue': 'Helvetica Neue',
            'TimesNewRoman': 'Times New Roman',
            'Times-Roman': 'Times New Roman',
            'Courier': 'Courier New',
            'CourierNew': 'Courier New',
        }

        return font_map.get(font, font)

    def _verify_svg(self, svg_path: Path) -> None:
        """Verify the generated SVG has the expected content."""
        try:
            with open(svg_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # Count elements
            text_count = content.count('<text ')
            path_count = content.count('<path ')
            use_count = content.count('<use ')

            # Check dimensions
            width_match = re.search(r'width="([0-9.]+)"', content)
            height_match = re.search(r'height="([0-9.]+)"', content)

            if width_match and height_match:
                w = float(width_match.group(1))
                h = float(height_match.group(1))
                logger.info(f"Final SVG: {w:.0f} x {h:.0f} px")

            logger.info(f"Elements: {text_count} <text>, {path_count} <path>, {use_count} <use>")

            if text_count > 0:
                logger.info("TEXT IS EDITABLE")
            else:
                logger.warning("No editable <text> elements found")

        except Exception as e:
            logger.debug(f"Verify failed: {e}")


# Convenience function
def convert_ai_to_svg(
    ai_path: str,
    output_path: Optional[str] = None,
    dpi: int = DEFAULT_EXPORT_DPI,
    text_to_path: bool = False
) -> str:
    """
    Convert AI file to SVG with editable text.

    Args:
        ai_path: Path to .ai file
        output_path: Output path (optional)
        dpi: Target DPI (default: 675)
        text_to_path: If True, convert text to paths (not editable)

    Returns:
        Path to output SVG file
    """
    converter = AIConverter()
    result = converter.convert_to_svg(
        ai_path=Path(ai_path),
        output_path=Path(output_path) if output_path else None,
        dpi=dpi,
        text_to_path=text_to_path
    )
    return str(result)


# CLI usage
if __name__ == "__main__":
    import sys
    import fitz  # Import here to use flags

    logging.basicConfig(
        level=logging.INFO,
        format='%(message)s'
    )

    if len(sys.argv) < 2:
        print("AI to SVG Converter - Editable Text @ 675 DPI")
        print("=" * 50)
        print("\nUsage:")
        print("  python ai_converter.py <input.ai> [output.svg] [options]")
        print("\nOptions:")
        print("  --dpi=N          Set DPI (default: 675)")
        print("  --text-to-path   Convert text to paths (not editable)")
        print("\nExamples:")
        print("  python ai_converter.py label.ai")
        print("  python ai_converter.py label.ai output.svg")
        print("  python ai_converter.py label.ai --dpi=300")
        print("  python ai_converter.py label.ai output.svg --text-to-path")
        sys.exit(1)

    # Parse arguments
    input_file = Path(sys.argv[1])
    output_file = None
    text_to_path = False
    dpi = DEFAULT_EXPORT_DPI

    for arg in sys.argv[2:]:
        if arg.startswith('--dpi='):
            dpi = int(arg.split('=')[1])
        elif arg == '--text-to-path':
            text_to_path = True
        elif not arg.startswith('--'):
            output_file = Path(arg)

    print(f"\nInput:  {input_file}")
    print(f"Output: {output_file or input_file.with_suffix('.svg')}")
    print(f"DPI:    {dpi}")
    print(f"Mode:   {'text-to-path' if text_to_path else 'editable text'}")
    print("-" * 50)

    try:
        converter = AIConverter()
        result = converter.convert_to_svg(
            ai_path=input_file,
            output_path=output_file,
            text_to_path=text_to_path,
            dpi=dpi
        )
        print("-" * 50)
        print(f"SUCCESS: {result}")

    except AIConverterError as e:
        print(f"\nERROR: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\nUNEXPECTED ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
