"""AI to SVG converter using PyMuPDF - with EDITABLE TEXT at 675 DPI"""

from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple, Union
import logging
import re
import html
import base64
from io import BytesIO

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
        dpi: int = DEFAULT_EXPORT_DPI,
        return_metadata: bool = False
    ) -> Union[Path, Tuple[Path, Dict[str, Any]]]:
        """
        Convert AI to SVG with editable text @ specified DPI.

        Args:
            ai_path: Path to .ai file
            output_path: Output path (default: same as input with .svg)
            text_to_path: False = editable <text> (default), True = paths
            dpi: Target DPI (default: 675)
            return_metadata: If True, return tuple (svg_path, metadata_dict)

        Returns:
            Path to output SVG, or tuple(path, metadata) if return_metadata=True
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

                # Extract embeddable fonts for @font-face embedding
                embedded_fonts = self._extract_embeddable_fonts(doc)

                # Generate SVG with graphics only (text as paths for positioning reference)
                svg_content = page.get_svg_image()

                # Remove the text paths from SVG (we'll add real <text> elements)
                svg_content = self._remove_text_paths(svg_content)

                # Apply scale to SVG dimensions
                svg_content = self._apply_scale_to_svg(svg_content, scale)

                # Add editable text elements with embedded fonts
                svg_content = self._add_text_elements(svg_content, text_data, scale, embedded_fonts)

            doc.close()

            # Write output
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(svg_content)

            # Verify result
            self._verify_svg(output_path)

            # Check for garbled text (font encoding issues)
            fallback_needed = self._detect_garbled_text(svg_content)
            metadata = {'fallback_needed': fallback_needed}

            logger.info(f"SUCCESS: {output_path}")
            if return_metadata:
                return output_path, metadata
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

    def _build_cff_decode_map(self, doc, page) -> Dict[str, Dict[int, str]]:
        """Build decode maps for CFF fonts with custom encoding (gidNNNNN glyphs).

        Some AI files embed CFF fonts (e.g. AcuminVariableConcept) where glyph names
        are opaque GID references (gid00131, gid00002, etc.) instead of standard
        names (A, B, space). PyMuPDF can't map these to Unicode and outputs U+FFFD.

        Solution: parse the PDF content stream to extract raw character codes,
        then map through CFF charset -> GID -> Unicode.

        Returns:
            Dict mapping PDF_encoding_name (e.g. 'T1_1') -> {raw_code: unicode_char}
        """
        decode_maps = {}
        fonts = page.get_fonts(full=True)
        for f in fonts:
            xref, ext, _, name, encoding = f[0], f[1], f[2], f[3], f[4]
            if ext != 'cff':
                continue

            try:
                from fontTools.cffLib import CFFFontSet
                cff_bytes = doc.extract_font(xref)[3]
                if not cff_bytes:
                    continue

                cff = CFFFontSet()
                cff.decompile(BytesIO(cff_bytes), None)
                charset = cff[0].charset

                # Only decode fonts with opaque gidNNNNN glyph names
                has_gid_names = any(g.startswith('gid') for g in charset if g != '.notdef')
                if not has_gid_names:
                    continue

                # Build GID -> Unicode (width-matching + standard fallback)
                gid_to_unicode = self._build_gid_to_unicode_from_widths(doc, xref, cff_bytes, charset)

                # Build charset_index -> Unicode from GID numbers
                index_to_unicode = {}
                for idx, glyph_name in enumerate(charset):
                    if idx == 0:
                        continue
                    if glyph_name.startswith('gid'):
                        try:
                            gid = int(glyph_name[3:])
                            ch = gid_to_unicode.get(gid)
                            if ch:
                                index_to_unicode[idx] = ch
                        except ValueError:
                            pass

                if not index_to_unicode:
                    continue

                # Parse content stream to find raw char codes for this font's encoding
                raw_codes = self._extract_raw_codes_from_content_stream(doc, page, encoding)
                if not raw_codes:
                    continue

                # Determine offset: min raw code maps to charset[1]
                min_code = min(raw_codes)
                offset = min_code - 1

                # Build final decode map: raw_code -> unicode
                code_map = {}
                for idx, ch in index_to_unicode.items():
                    code_map[idx + offset] = ch

                if code_map:
                    decode_maps[encoding] = code_map
                    sample = ''.join(code_map.get(c, '?') for c in raw_codes[:30])
                    logger.info(f"✓ CFF decode: font='{name}' encoding='{encoding}', "
                                f"{len(code_map)} mappings, decoded: '{sample}'")

            except ImportError:
                logger.warning("fontTools not installed - CFF decode unavailable. Install: pip install fonttools")
                return {}
            except Exception as e:
                logger.debug(f"CFF decode failed for {name}: {e}")

        return decode_maps

    def _extract_raw_codes_from_content_stream(self, doc, page, font_encoding: str) -> List[int]:
        """Extract raw character codes from PDF content stream for a specific font.

        Parses Tf (font selection) and TJ/Tj (text showing) operators to get
        the original byte values before PyMuPDF's Unicode conversion.
        """
        raw_codes = []
        try:
            contents = page.get_contents()
            for content_xref in contents:
                stream = doc.xref_stream(content_xref).decode('latin-1', errors='replace')
                current_font = ''

                for line in stream.split('\n'):
                    line = line.strip()

                    # Font selection: /T1_1 1 Tf
                    font_match = re.match(r'/(\S+)\s+[\d.]+\s+Tf', line)
                    if font_match:
                        current_font = font_match.group(1)
                        continue

                    if current_font != font_encoding:
                        continue
                    if 'TJ' not in line and 'Tj' not in line:
                        continue

                    # Extract raw byte codes from PDF string literals
                    for part in re.findall(r'\(([^)]*)\)', line):
                        i = 0
                        while i < len(part):
                            if part[i] == '\\' and i + 1 < len(part):
                                i += 1
                                if part[i] == 'r':
                                    raw_codes.append(0x0d)
                                    i += 1
                                elif part[i] == 'n':
                                    raw_codes.append(0x0a)
                                    i += 1
                                elif part[i] == 't':
                                    raw_codes.append(0x09)
                                    i += 1
                                elif part[i].isdigit():
                                    octal = ''
                                    while i < len(part) and part[i].isdigit() and len(octal) < 3:
                                        octal += part[i]
                                        i += 1
                                    raw_codes.append(int(octal, 8))
                                else:
                                    raw_codes.append(ord(part[i]))
                                    i += 1
                            else:
                                raw_codes.append(ord(part[i]))
                                i += 1

        except Exception as e:
            logger.debug(f"Content stream parse failed for {font_encoding}: {e}")

        return raw_codes

    def _build_gid_to_unicode_from_widths(self, doc, font_xref, cff_bytes, charset) -> Dict[int, str]:
        """Build GID -> Unicode mapping by matching glyph widths.

        Universal approach: compare the width of each CFF glyph (by GID)
        against widths of all printable Unicode characters in the same font.
        Width matching is unique enough for most characters.

        Falls back to standard Adobe CID ordering for ambiguous matches.
        """
        import fitz

        try:
            font_obj = fitz.Font(fontbuffer=cff_bytes)
        except Exception:
            return self._build_gid_to_unicode_standard()

        # Get widths from PDF font dict for each char code
        font_dict = doc.xref_object(font_xref)
        fc_match = re.search(r'/FirstChar\s+(\d+)', font_dict)
        widths_match = re.search(r'/Widths\s*\[([^\]]+)\]', font_dict)

        if not fc_match or not widths_match:
            return self._build_gid_to_unicode_standard()

        first_char = int(fc_match.group(1))
        pdf_widths = [int(round(float(w))) for w in widths_match.group(1).split()]

        # Build width -> Unicode char map from the font
        # Use text_length at fontsize=1000 for integer precision
        unicode_by_width = {}
        for code in range(32, 127):
            ch = chr(code)
            w = int(round(font_obj.text_length(ch, fontsize=1000)))
            if w > 0:
                if w not in unicode_by_width:
                    unicode_by_width[w] = []
                unicode_by_width[w].append(ch)

        # Map charset GIDs by matching PDF widths against font unicode widths
        gid_map = {}
        # charset[0] = .notdef, charset[1] = first glyph at first_char, etc.
        for idx in range(1, len(charset)):
            glyph_name = charset[idx]
            if not glyph_name.startswith('gid'):
                continue
            try:
                gid = int(glyph_name[3:])
            except ValueError:
                continue

            # Width from PDF /Widths array
            width_idx = idx - 1  # charset[1] -> Widths[0]
            if width_idx >= len(pdf_widths):
                continue
            w = pdf_widths[width_idx]

            candidates = unicode_by_width.get(w, [])
            if len(candidates) == 1:
                gid_map[gid] = candidates[0]
            elif len(candidates) > 1:
                # Ambiguous - use standard ordering as tiebreaker
                standard = self._build_gid_to_unicode_standard()
                if gid in standard:
                    gid_map[gid] = standard[gid]
                else:
                    gid_map[gid] = candidates[0]  # best guess

        # Start with standard mapping, override only with UNIQUE width matches
        result = self._build_gid_to_unicode_standard()

        unique_matches = {gid: ch for gid, ch in gid_map.items() if gid not in result}
        if unique_matches:
            result.update(unique_matches)
            logger.info(f"✓ Width-matched {len(unique_matches)} extra GIDs to Unicode")

        return result

    @staticmethod
    def _build_gid_to_unicode_standard() -> Dict[int, str]:
        """Standard Adobe CID GID -> Unicode mapping for Latin fonts.

        Based on Adobe Identity ordering used in CFF subset fonts:
        GID 1=space, 2-27=A-Z, 28-53=a-z, then extended Latin and punctuation.
        """
        m = {1: ' '}
        # A-Z: GID 2-27
        for i in range(26):
            m[2 + i] = chr(ord('A') + i)
        # a-z: GID 28-53
        for i in range(26):
            m[28 + i] = chr(ord('a') + i)
        # Extended Latin (accented) - common Adobe CID positions
        accented = [
            (54, 'À'), (55, 'Á'), (56, 'Â'), (57, 'Ã'), (58, 'Ä'), (59, 'Å'),
            (60, 'Æ'), (61, 'Ç'), (62, 'È'), (63, 'É'), (64, 'Ê'), (65, 'Ë'),
            (66, 'Ì'), (67, 'Í'), (68, 'Î'), (69, 'Ï'), (70, 'Ð'), (71, 'Ñ'),
            (72, 'Ò'), (73, 'Ó'), (74, 'Ô'), (75, 'Õ'), (76, 'Ö'), (78, 'Ø'),
            (79, 'Ù'), (80, 'Ú'), (81, 'Û'), (82, 'Ü'), (83, 'Ý'), (84, 'Þ'),
            (85, 'ß'), (86, 'à'), (87, 'á'), (88, 'â'), (89, 'ã'), (90, 'ä'),
            (91, 'å'), (92, 'æ'), (93, 'ç'), (94, 'è'), (95, 'é'), (96, 'ê'),
            (97, 'ë'), (98, 'ì'), (99, 'í'), (100, 'î'), (101, 'ï'), (102, 'ð'),
            (103, 'ñ'), (104, 'ò'), (105, 'ó'), (106, 'ô'), (107, 'õ'), (108, 'ö'),
            (110, 'ø'), (111, 'ù'), (112, 'ú'), (113, 'û'), (114, 'ü'), (115, 'ý'),
            (116, 'þ'), (117, 'ÿ'),
        ]
        for gid, ch in accented:
            m[gid] = ch
        # Digits 0-9: GID 131-140
        for i in range(10):
            m[131 + i] = chr(ord('0') + i)
        # Punctuation
        punct = [
            (141, '!'), (142, '"'), (143, '#'), (144, '$'), (145, '%'),
            (146, '&'), (147, "'"), (148, '('), (149, ')'), (150, '*'),
            (151, '+'), (152, ','), (153, '-'), (154, '.'), (155, '/'),
            (156, ':'), (157, ';'), (158, '<'), (159, '='), (160, '>'),
            (161, '?'), (162, '@'), (163, '.'), (165, ':'), (166, ';'),
        ]
        for gid, ch in punct:
            m[gid] = ch
        return m

    def _extract_text_data(self, page) -> List[Dict[str, Any]]:
        """Extract text with positions, fonts, sizes, colors from page."""
        import fitz
        text_data = []

        # Build CFF decode maps for fonts with custom encoding
        doc = page.parent
        cff_decode_maps = self._build_cff_decode_map(doc, page)

        # Build per-font ordered decoded text from content stream
        # so we can replace garbled spans in order
        font_decoded_texts = {}
        for encoding, code_map in cff_decode_maps.items():
            raw_codes = self._extract_raw_codes_from_content_stream(doc, page, encoding)
            font_decoded_texts[encoding] = ''.join(code_map.get(c, '?') for c in raw_codes)

        # Track position in decoded text per font encoding
        font_decode_pos = {enc: 0 for enc in font_decoded_texts}

        # Map PDF encoding names to font names used by PyMuPDF
        # e.g. T1_1 -> AcuminVariableConcept
        encoding_to_pymupdf_font = {}
        for f in page.get_fonts(full=True):
            name, encoding = f[3], f[4]
            base_name = name.split('+')[-1] if '+' in name else name
            encoding_to_pymupdf_font[encoding] = base_name

        # Reverse: pymupdf font name -> encoding
        pymupdf_font_to_encoding = {v: k for k, v in encoding_to_pymupdf_font.items()}

        # Get detailed text info
        text_dict = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)

        for block in text_dict.get("blocks", []):
            if block.get("type") != 0:
                continue

            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    text = span.get("text", "").strip()
                    if not text:
                        continue

                    font = span.get("font", "Arial")
                    base_font = font.split('+')[-1] if '+' in font else font

                    # Check if this font needs CFF decoding
                    encoding = pymupdf_font_to_encoding.get(base_font)
                    if encoding and encoding in font_decoded_texts:
                        # Replace garbled text with decoded version
                        decoded_full = font_decoded_texts[encoding]
                        pos = font_decode_pos[encoding]
                        char_count = len(text)
                        decoded_text = decoded_full[pos:pos + char_count]
                        font_decode_pos[encoding] = pos + char_count

                        if decoded_text:
                            logger.info(f"✓ CFF decoded: '{text[:20]}...' -> '{decoded_text}'")
                            text = decoded_text

                    # Get position
                    bbox = span.get("bbox", [0, 0, 0, 0])
                    origin = span.get("origin", (bbox[0], bbox[3]))

                    size = span.get("size", 12)
                    color_int = span.get("color", 0)
                    color_hex = self._int_to_hex_color(color_int)

                    flags = span.get("flags", 0)
                    is_bold = bool(flags & 2**4)
                    is_italic = bool(flags & 2**1)

                    font_name_upper = font.upper()
                    if any(kw in font_name_upper for kw in ['BOLD', 'BLACK', 'HEAVY', 'SEMIBOLD', 'DEMIBOLD']):
                        is_bold = True

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
        # COMMENTED OUT: This was removing background shapes too!
        # svg = re.sub(r'<use[^>]*xlink:href="#g[0-9]+"[^>]*/>', '', svg)

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

    # System fonts that don't need embedding (available everywhere)
    SYSTEM_FONTS = {
        'arial', 'arialmt', 'arial-boldmt', 'arial-italicmt', 'arial-bolditaliicmt',
        'helvetica', 'helveticaneue', 'times', 'timesnewroman', 'times-roman',
        'courier', 'couriernew', 'verdana', 'georgia', 'trebuchetms',
        'impact', 'comicsansms', 'tahoma', 'lucidagrande', 'palatino',
    }

    def _extract_embeddable_fonts(self, doc) -> Dict[str, str]:
        """Extract TTF fonts from AI/PDF that have sufficient character coverage.

        Returns dict: {clean_font_name: base64_encoded_ttf_data}
        Only includes non-system fonts with >= 50 unique glyphs.
        """
        MIN_GLYPHS = 50
        embedded_fonts = {}

        try:
            page = doc[0]
            fonts = page.get_fonts(full=True)

            for f in fonts:
                xref, ext, ftype, name, refname, encoding = f[:6]

                # Only embed TTF fonts (CFF subsets are usually too small)
                if ext != 'ttf':
                    logger.info(f"Font {name}: skipping ({ext} format)")
                    continue

                # Clean the font name (remove subset prefix like "HBECWF+")
                clean_name = re.sub(r'^[A-Z]{6}\+', '', name)

                # Skip system fonts (already available, no need to embed)
                base_name = re.sub(r'-(Bold|Italic|Regular|Medium|Light|Book).*$', '', clean_name, flags=re.IGNORECASE)
                if base_name.lower().replace(' ', '') in self.SYSTEM_FONTS:
                    logger.info(f"Font {name}: system font, skipping embed")
                    continue

                # Skip if we already have this font family
                if clean_name in embedded_fonts:
                    continue

                try:
                    font_data = doc.extract_font(xref)
                    fname, fext, fsubtype, fbuffer = font_data

                    if not fbuffer or len(fbuffer) < 100:
                        continue

                    # Check glyph count
                    from fontTools.ttLib import TTFont
                    tt = TTFont(BytesIO(fbuffer))
                    cmap = tt.getBestCmap()
                    glyph_count = len(cmap) if cmap else 0
                    tt.close()

                    if glyph_count < MIN_GLYPHS:
                        logger.info(f"Font {name}: only {glyph_count} glyphs, skipping")
                        continue

                    # Base64 encode the font data
                    b64_data = base64.b64encode(fbuffer).decode('ascii')
                    embedded_fonts[clean_name] = b64_data

                    # Also save TTF to temp/fonts/ so TextFormatter can use it for measuring
                    try:
                        import config
                        fonts_dir = config.TEMP_DIR / 'fonts'
                        fonts_dir.mkdir(parents=True, exist_ok=True)
                        ttf_path = fonts_dir / f"{clean_name}.ttf"
                        with open(ttf_path, 'wb') as ttf_file:
                            ttf_file.write(fbuffer)
                        logger.info(f"Font {name}: saved to {ttf_path}")
                    except Exception as save_err:
                        logger.warning(f"Font {name}: couldn't save TTF: {save_err}")

                    logger.info(f"Font {name}: extracted ({glyph_count} glyphs, {len(fbuffer)} bytes) as '{clean_name}'")

                except Exception as e:
                    logger.warning(f"Font {name}: extraction failed: {e}")
                    continue

        except Exception as e:
            logger.warning(f"Font extraction failed: {e}")

        return embedded_fonts

    def _build_font_face_css(self, embedded_fonts: Dict[str, str], text_data: List[Dict]) -> str:
        """Build @font-face CSS rules for embedded fonts.

        Also creates aliases: if text uses 'Gotham' but only 'GothamMedium' is embeddable,
        add a @font-face for 'Gotham' using GothamMedium data.
        """
        if not embedded_fonts:
            return ''

        # Collect all font families used in the text data
        used_fonts = set()
        for item in text_data:
            clean_name = self._clean_font_name(item['font'])
            used_fonts.add(clean_name)

        css_rules = []
        covered_families = set()  # Font families that have @font-face rules

        # First pass: create @font-face for directly matched fonts
        for font_name, b64_data in embedded_fonts.items():
            clean_name = self._clean_font_name(font_name)
            css_rules.append(
                f"@font-face {{\n"
                f"  font-family: '{clean_name}';\n"
                f"  src: url('data:font/truetype;base64,{b64_data}') format('truetype');\n"
                f"}}"
            )
            covered_families.add(clean_name)
            logger.info(f"@font-face: '{clean_name}' (direct)")

        # Second pass: create aliases for fonts that are used but not directly available
        # e.g., text uses 'Gotham' but we only have 'GothamMedium'
        aliases = {}  # {alias_name: source_font_name}
        for used_font in used_fonts:
            if used_font in covered_families:
                continue

            # Find a similar embedded font (same base name)
            best_match = None
            for font_name in embedded_fonts:
                clean = self._clean_font_name(font_name)
                # Check if names share a common root (e.g., Gotham ~ GothamMedium)
                if used_font.lower() in clean.lower() or clean.lower() in used_font.lower():
                    best_match = font_name
                    break

            if best_match:
                b64_data = embedded_fonts[best_match]
                css_rules.append(
                    f"@font-face {{\n"
                    f"  font-family: '{used_font}';\n"
                    f"  src: url('data:font/truetype;base64,{b64_data}') format('truetype');\n"
                    f"}}"
                )
                covered_families.add(used_font)
                aliases[used_font] = best_match
                logger.info(f"@font-face: '{used_font}' (alias for {best_match})")

        # Save alias TTFs so TextFormatter can find them for text measurement
        if aliases:
            try:
                import config
                fonts_dir = config.TEMP_DIR / 'fonts'
                fonts_dir.mkdir(parents=True, exist_ok=True)
                for alias_name, source_name in aliases.items():
                    src_path = fonts_dir / f"{source_name}.ttf"
                    dst_path = fonts_dir / f"{alias_name}.ttf"
                    if src_path.exists() and not dst_path.exists():
                        import shutil
                        shutil.copy2(src_path, dst_path)
                        logger.info(f"Font alias: {dst_path.name} → {src_path.name}")
            except Exception as e:
                logger.warning(f"Font alias save failed: {e}")

        if not css_rules:
            return ''

        return '<style type="text/css">\n' + '\n'.join(css_rules) + '\n</style>\n'

    def _add_text_elements(self, svg: str, text_data: List[Dict], scale: float, embedded_fonts: Dict[str, str] = None) -> str:
        """Add editable <text> elements to SVG with embedded @font-face."""
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

            # Build font style - simple 1:1 conversion from original
            font_family = self._clean_font_name(item["font"])
            font_weight = "bold" if item["bold"] else "normal"
            font_style = "italic" if item["italic"] else "normal"

            # Create simple text element - NO artificial enhancements, just preserve original
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

        # Build @font-face CSS for embedded fonts
        font_face_css = ''
        if embedded_fonts:
            font_face_css = self._build_font_face_css(embedded_fonts, text_data)

        # Insert font-face CSS + text block before </svg>
        text_block = ''
        if font_face_css:
            text_block += '\n<!-- EMBEDDED FONTS -->\n'
            # Insert into <defs> if it exists, otherwise add before text
            if '<defs>' in svg:
                svg = svg.replace('<defs>', '<defs>\n' + font_face_css)
                logger.info("Embedded @font-face CSS into <defs>")
            else:
                text_block += font_face_css

        text_block += '\n<!-- EDITABLE TEXT - Generated at {} DPI -->\n'.format(int(scale * 72))
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

    def _detect_garbled_text(self, svg_content: str) -> bool:
        """Detect if text extraction produced � (Unicode replacement chars).

        Returns True if ≥3 consecutive � characters found in any aria-label.
        This indicates font encoding issues.

        Args:
            svg_content: SVG content to check

        Returns:
            True if garbled text detected, False otherwise
        """
        # Find all aria-label attributes
        aria_labels = re.findall(r'aria-label="([^"]*)"', svg_content)

        for label in aria_labels:
            # Count consecutive � characters
            garbled_count = label.count('�')

            # If ≥3 garbled chars, extraction failed
            if garbled_count >= 3:
                logger.warning(f"⚠️  Garbled text detected: '{label[:50]}...' ({garbled_count} � chars)")
                return True

        return False

    # ========================================================================
    # HYBRID PATHS + TEXT: Pixel-perfect fallback for label generation
    # ========================================================================

    def create_hybrid_base(self, ai_path: Path, output_path: Path, text_areas: Dict, scale: float = 9.375):
        """Create hybrid SVG base: text as paths (pixel-perfect) + embedded fonts.

        Returns dict with:
          - svg_path: path to the base SVG file
          - font_css: @font-face CSS for embedded fonts
          - use_elements: list of <use data-text> info grouped by area
          - scale: the scale factor used
          - areas_unscaled: text_areas converted to unscaled SVG coordinates
          - font_info: dict of {area_name: {font_family, font_size, fill, font_weight}} from original
        """
        import fitz

        doc = fitz.open(str(ai_path))
        page = doc[0]
        rect = page.rect

        # Get SVG with text as paths (pixel-perfect rendering)
        svg = page.get_svg_image()

        # Extract embeddable fonts
        embedded_fonts = self._extract_embeddable_fonts(doc)
        font_css = ''
        if embedded_fonts:
            # Build CSS - we need text_data for alias matching
            text_data = self._extract_text_data(page)
            font_css = self._build_font_face_css(embedded_fonts, text_data)

        # Extract font info for each area from text_data (before we lose it)
        font_info = self._extract_font_info_for_areas(page, text_areas, scale)

        # Parse all <use data-text> elements
        use_pattern = r'<use\s+data-text="([^"]*)"[^>]*transform="matrix\([^,]+,[^,]+,[^,]+,[^,]+,([^,]+),([^)]+)\)"[^>]*/>'
        all_uses = []
        for m in re.finditer(use_pattern, svg):
            all_uses.append({
                'char': m.group(1),
                'x': float(m.group(2)),
                'y': float(m.group(3)),
                'full_match': m.group(0),
            })

        # Convert areas to unscaled coordinates
        areas_unscaled = {}
        for name, area in text_areas.items():
            areas_unscaled[name] = {
                'x': area['x'] / scale, 'y': area['y'] / scale,
                'width': area['width'] / scale, 'height': area['height'] / scale,
            }

        # Find which <use> elements fall within each area
        elements_by_area = {}
        for area_name, area in areas_unscaled.items():
            y_min, y_max = area['y'], area['y'] + area['height']
            x_min, x_max = area['x'], area['x'] + area['width']
            elements_by_area[area_name] = []
            for u in all_uses:
                if y_min <= u['y'] <= y_max and x_min - 5 <= u['x'] <= x_max + 5:
                    elements_by_area[area_name].append(u['full_match'])

        # Also collect garbled elements (for SKU area)
        garbled_elements = [u['full_match'] for u in all_uses if u['char'] == '&#xfffd;']

        # Set up SVG dimensions with viewBox
        new_w = rect.width * scale
        new_h = rect.height * scale
        svg = re.sub(r'width="[^"]*"', f'width="{new_w:.2f}"', svg, count=1)
        svg = re.sub(r'height="[^"]*"', f'height="{new_h:.2f}"', svg, count=1)
        if 'viewBox' not in svg:
            svg = svg.replace(
                f'height="{new_h:.2f}"',
                f'height="{new_h:.2f}" viewBox="0 0 {rect.width} {rect.height}"',
                1
            )

        # Write base SVG
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(svg)

        doc.close()

        logger.info(f"[Hybrid] Base SVG: {output_path} ({new_w:.0f}x{new_h:.0f})")
        logger.info(f"[Hybrid] Areas: {list(elements_by_area.keys())}, "
                     f"elements to remove: {sum(len(v) for v in elements_by_area.values())} + {len(garbled_elements)} garbled")

        return {
            'svg_path': output_path,
            'font_css': font_css,
            'elements_by_area': elements_by_area,
            'garbled_elements': garbled_elements,
            'scale': scale,
            'areas_unscaled': areas_unscaled,
            'font_info': font_info,
            'svg_width': new_w,
            'svg_height': new_h,
        }

    def _extract_font_info_for_areas(self, page, text_areas: Dict, scale: float) -> Dict:
        """Extract original font styling for each text area from the PDF page."""
        text_data = self._extract_text_data(page)

        font_info = {}
        for area_name, area in text_areas.items():
            # Convert area to unscaled coords
            y_min = area['y'] / scale
            y_max = (area['y'] + area['height']) / scale
            x_min = area['x'] / scale
            x_max = (area['x'] + area['width']) / scale

            # Find text spans within this area
            for td in text_data:
                if y_min <= td['y'] <= y_max and x_min - 5 <= td['x'] <= x_max + 5:
                    clean_font = self._clean_font_name(td['font'])
                    font_info[area_name] = {
                        'font_family': clean_font,
                        'font_size': td['size'],  # unscaled
                        'fill': td['color'],
                        'font_weight': 'bold' if td['bold'] else 'normal',
                        'font_style': 'italic' if td['italic'] else 'normal',
                    }
                    break  # Use first match

        # Fallback for SKU (might be garbled, use defaults)
        if 'sku' not in font_info:
            font_info['sku'] = {
                'font_family': 'Arial',
                'font_size': 2.5,
                'fill': '#ffffff',
                'font_weight': 'normal',
                'font_style': 'normal',
            }

        info_str = ', '.join(f'{k}: {v["font_family"]} {v["font_size"]:.1f}px {v["fill"]}' for k, v in font_info.items())
        logger.info(f"[Hybrid] Font info: {info_str}")
        return font_info

    # Bundled Google Fonts directory
    _FONT_DIR = Path(__file__).parent / 'fonts' / 'google'

    # Commercial font → Google Font equivalent mapping
    # Format: 'OriginalFont': 'GoogleFontFamily'
    # The weight variant is resolved automatically (Regular, Bold, Medium, etc.)
    FONT_ALTERNATIVES = {
        # Gotham family → Montserrat (geometric sans, closest match)
        'Gotham': 'Montserrat', 'Gotham-Bold': 'Montserrat', 'GothamMedium': 'Montserrat',
        'Gotham-Medium': 'Montserrat', 'GothamBook': 'Montserrat', 'Gotham-Book': 'Montserrat',
        'GothamLight': 'Montserrat', 'Gotham-Light': 'Montserrat',
        'Gotham-Black': 'Montserrat', 'GothamBlack': 'Montserrat',
        # Helvetica/Helvetica Neue → Inter (modern, metrically similar)
        'Helvetica': 'Inter', 'HelveticaNeue': 'Inter', 'Helvetica-Neue': 'Inter',
        'HelveticaNeue-Bold': 'Inter', 'HelveticaNeue-Medium': 'Inter',
        'HelveticaNeue-Light': 'Inter', 'HelveticaNeue-Thin': 'Inter',
        # Futura → Nunito (geometric sans with rounded feel)
        'Futura': 'Nunito', 'Futura-Bold': 'Nunito', 'Futura-Medium': 'Nunito',
        'FuturaPT': 'Nunito', 'Futura-Book': 'Nunito',
        # Avenir → NunitoSans (geometric, clean)
        'Avenir': 'NunitoSans', 'Avenir-Book': 'NunitoSans', 'Avenir-Medium': 'NunitoSans',
        'Avenir-Heavy': 'NunitoSans', 'Avenir-Black': 'NunitoSans',
        'AvenirNext': 'NunitoSans', 'Avenir-Next': 'NunitoSans',
        # Proxima Nova → Montserrat (very similar geometric sans)
        'ProximaNova': 'Montserrat', 'Proxima-Nova': 'Montserrat',
        'ProximaNova-Bold': 'Montserrat', 'ProximaNova-Regular': 'Montserrat',
        'ProximaNova-Semibold': 'Montserrat',
        # Century Gothic → Poppins (geometric, circular)
        'CenturyGothic': 'Poppins', 'Century-Gothic': 'Poppins',
        # Gill Sans → Lato (humanist sans)
        'GillSans': 'Lato', 'Gill-Sans': 'Lato', 'GillSans-Bold': 'Lato',
        # Franklin Gothic → LibreFranklin (direct open-source clone)
        'FranklinGothic': 'LibreFranklin', 'Franklin-Gothic': 'LibreFranklin',
        'ITC Franklin Gothic': 'LibreFranklin',
        # Trade Gothic → SourceSans3
        'TradeGothic': 'SourceSans3', 'Trade-Gothic': 'SourceSans3',
        # DIN → DMSans (industrial geometric)
        'DIN': 'DMSans', 'DINPro': 'DMSans', 'DIN-Pro': 'DMSans',
        'DINNextLTPro': 'DMSans', 'DINCondensed': 'Oswald',
        # Frutiger → OpenSans (humanist sans, similar proportions)
        'Frutiger': 'OpenSans', 'Frutiger-Bold': 'OpenSans',
        # Univers → IBMPlexSans (neo-grotesque)
        'Univers': 'Roboto', 'Univers-Bold': 'Roboto',
        # Myriad Pro → SourceSans3 (Adobe's open alternative)
        'MyriadPro': 'SourceSans3', 'Myriad-Pro': 'SourceSans3',
        'MyriadPro-Regular': 'SourceSans3', 'MyriadPro-Bold': 'SourceSans3',
        # Acumin → Inter (modern grotesque)
        'Acumin': 'Inter', 'AcuminPro': 'Inter', 'AcuminVariableConcept': 'Inter',
        # Garamond → EBGaramond (serif, direct match)
        'Garamond': 'EBGaramond', 'AGaramond': 'EBGaramond', 'Adobe-Garamond': 'EBGaramond',
        'GaramondPremrPro': 'EBGaramond',
        # Baskerville → LibreBaskerville (serif, direct match)
        'Baskerville': 'LibreBaskerville', 'Baskerville-Bold': 'LibreBaskerville',
        # Bodoni → PlayfairDisplay (high-contrast serif)
        'Bodoni': 'PlayfairDisplay', 'BodoniMT': 'PlayfairDisplay',
        # Palatino → Lora (serif, similar feel)
        'Palatino': 'Lora', 'PalatinoLinotype': 'Lora',
        # Times/Times New Roman → Lora (serif)
        'TimesNewRoman': 'Lora', 'Times-Roman': 'Lora', 'Times': 'Lora',
        # Arial → OpenSans, Roboto (similar neo-grotesque)
        'Arial': 'OpenSans', 'ArialMT': 'OpenSans', 'Arial-BoldMT': 'OpenSans',
        'Arial-Bold': 'OpenSans',
        # Calibri → OpenSans (humanist sans)
        'Calibri': 'OpenSans', 'Calibri-Bold': 'OpenSans',
        # Verdana → NunitoSans (wide sans)
        'Verdana': 'NunitoSans',
        # Tahoma → Roboto
        'Tahoma': 'Roboto',
        # Trebuchet → Raleway
        'TrebuchetMS': 'Raleway', 'Trebuchet': 'Raleway',
        # Segoe UI → Inter
        'SegoeUI': 'Inter', 'Segoe-UI': 'Inter',
        # Roboto (already Google Font, map to itself)
        'Roboto': 'Roboto',
        # Impact → Oswald (condensed, heavy)
        'Impact': 'Oswald',
    }

    # Weight name mapping for font filenames
    _WEIGHT_FILE_MAP = {
        'bold': 'Bold', 'normal': 'Regular', 'medium': 'Medium',
        'light': 'Light', 'thin': 'Light', 'black': 'Black',
        'heavy': 'ExtraBold', 'semibold': 'SemiBold', 'extrabold': 'ExtraBold',
    }

    def _get_pil_font(self, font_family: str, font_weight: str, size_px: int):
        """Get a PIL ImageFont for the given font family and weight.

        Uses bundled Google Fonts with automatic commercial→open mapping.
        Works on all platforms (macOS, Linux, Railway).
        """
        from PIL import ImageFont

        # Clean font name (remove subset prefix like LJIKFX+)
        clean = font_family.split('+')[-1] if '+' in font_family else font_family

        # Detect weight from font name if embedded (e.g. 'Gotham-Bold' → bold)
        detected_weight = font_weight
        for suffix in ['Bold', 'Black', 'Heavy', 'ExtraBold', 'SemiBold', 'Medium', 'Light', 'Thin']:
            if clean.endswith(suffix) or clean.endswith('-' + suffix):
                detected_weight = suffix.lower()
                break

        # 1. Find Google Font family from mapping
        google_family = self.FONT_ALTERNATIVES.get(clean)
        if not google_family:
            # Try without hyphens/spaces
            normalized = clean.replace('-', '').replace(' ', '')
            google_family = self.FONT_ALTERNATIVES.get(normalized)

        if google_family:
            weight_name = self._WEIGHT_FILE_MAP.get(detected_weight, 'Regular')
            font_path = self._FONT_DIR / f'{google_family}-{weight_name}.ttf'
            if font_path.exists():
                return ImageFont.truetype(str(font_path), size_px)
            # Try exact weight
            font_path = self._FONT_DIR / f'{google_family}-Bold.ttf' if detected_weight == 'bold' else self._FONT_DIR / f'{google_family}-Regular.ttf'
            if font_path.exists():
                return ImageFont.truetype(str(font_path), size_px)

        # 2. Try font name directly as Google Font (might already be a Google Font)
        normalized = clean.replace('-', '').replace(' ', '')
        weight_name = self._WEIGHT_FILE_MAP.get(detected_weight, 'Regular')
        for try_name in [clean, normalized]:
            font_path = self._FONT_DIR / f'{try_name}-{weight_name}.ttf'
            if font_path.exists():
                return ImageFont.truetype(str(font_path), size_px)

        # 3. Fallback: Montserrat (best general-purpose font)
        weight_name = self._WEIGHT_FILE_MAP.get(detected_weight, 'Regular')
        font_path = self._FONT_DIR / f'Montserrat-{weight_name}.ttf'
        if font_path.exists():
            return ImageFont.truetype(str(font_path), size_px)

        # 4. Try system fc-match
        import subprocess
        try:
            weight_str = 'bold' if font_weight == 'bold' else 'medium'
            result = subprocess.run(
                ['fc-match', f'{font_family}:weight={weight_str}', '--format=%{file}'],
                capture_output=True, text=True, timeout=5
            )
            if result.stdout and Path(result.stdout).exists():
                return ImageFont.truetype(result.stdout, size_px)
        except Exception:
            pass

        # 5. Last resort
        return ImageFont.load_default()

    def _fit_pil_text(self, draw, text: str, font_family: str, font_weight: str,
                      max_size_px: int, area_w: float, area_h: float):
        """Find the largest font size that fits text within area. Returns (font, text_w, text_h)."""
        size = max_size_px
        while size > 8:
            font = self._get_pil_font(font_family, font_weight, size)
            bbox = draw.textbbox((0, 0), text, font=font)
            tw = bbox[2] - bbox[0]
            th = bbox[3] - bbox[1]
            if tw <= area_w and th <= area_h:
                return font, tw, th
            size -= 1
        font = self._get_pil_font(font_family, font_weight, 8)
        bbox = draw.textbbox((0, 0), text, font=font)
        return font, bbox[2] - bbox[0], bbox[3] - bbox[1]

    @staticmethod
    def _hex_to_rgb(hex_color: str) -> tuple:
        """Convert '#rrggbb' to (r, g, b) tuple."""
        h = hex_color.lstrip('#')
        if len(h) == 6:
            return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
        return (0, 0, 0)

    def generate_hybrid_label(self, hybrid_base: Dict, product_data: Dict, output_dir: Path) -> Dict:
        """Generate a single label using PIL overlay approach.

        1. Remove target <use> elements from paths-only SVG
        2. Render cleaned SVG to PNG (CairoSVG - paths only, no font issues)
        3. Draw replacement text on PNG using PIL with system fonts
        4. Save as PNG, JPG, PDF

        Args:
            hybrid_base: dict from create_hybrid_base()
            product_data: {'Product': '...', 'Ingredients': '...', 'SKU': '...'}
            output_dir: directory to write output files

        Returns:
            dict with paths: {svg, png, jpg, pdf} or None on error
        """
        import cairosvg
        from PIL import Image, ImageDraw

        sku = product_data.get('SKU', 'UNKNOWN')
        sku_safe = sku.replace('/', '_').replace('\\', '_')
        product_name = product_data.get('Product', '')
        ingredients = product_data.get('Ingredients', '')

        # Step 1: Remove target <use> elements from SVG
        with open(hybrid_base['svg_path'], 'r', encoding='utf-8') as f:
            svg = f.read()

        removed = 0
        for area_name, elements in hybrid_base['elements_by_area'].items():
            for elem_text in elements:
                if elem_text in svg:
                    svg = svg.replace(elem_text, '', 1)
                    removed += 1
        for elem_text in hybrid_base['garbled_elements']:
            if elem_text in svg:
                svg = svg.replace(elem_text, '', 1)
                removed += 1

        logger.info(f"[Hybrid PIL] {sku}: removed {removed} <use> elements")

        # Step 2: Render cleaned SVG to PNG (paths only - CairoSVG handles this perfectly)
        output_dir.mkdir(parents=True, exist_ok=True)
        svg_path = output_dir / f'label_{sku_safe}.svg'
        with open(svg_path, 'w', encoding='utf-8') as f:
            f.write(svg)

        png_path = output_dir / f'label_{sku_safe}.png'
        try:
            svg_w = int(hybrid_base['svg_width'])
            svg_h = int(hybrid_base['svg_height'])
            cairosvg.svg2png(url=str(svg_path), write_to=str(png_path), output_width=svg_w, output_height=svg_h)
        except Exception as e:
            logger.error(f"[Hybrid PIL] SVG→PNG render failed for {sku}: {e}")
            return None

        # Load and add white background
        img = Image.open(png_path)
        if img.mode == 'RGBA':
            bg = Image.new('RGB', img.size, (255, 255, 255))
            bg.paste(img, mask=img.split()[3])
            img = bg

        draw = ImageDraw.Draw(img)
        scale = hybrid_base['scale']
        font_info = hybrid_base['font_info']
        text_areas_px = {k: v for k, v in hybrid_base.get('text_areas_px', {}).items()}

        # Use original pixel-coordinate areas (from create_hybrid_base input)
        # areas_unscaled * scale = pixel coordinates
        areas_px = {}
        for name, area in hybrid_base['areas_unscaled'].items():
            areas_px[name] = {
                'x': area['x'] * scale,
                'y': area['y'] * scale,
                'width': area['width'] * scale,
                'height': area['height'] * scale,
            }

        # Step 3: Draw text with PIL

        # Product name
        if 'product_name' in areas_px and product_name:
            fi = font_info.get('product_name', {'font_family': 'Gotham', 'font_size': 10, 'fill': '#ffffff', 'font_weight': 'bold'})
            area = areas_px['product_name']
            font_size_px = int(fi['font_size'] * scale)
            font, tw, th = self._fit_pil_text(draw, product_name, fi['font_family'], fi['font_weight'], font_size_px, area['width'], area['height'])
            x = area['x']
            y = area['y'] + (area['height'] - th) / 2
            color = self._hex_to_rgb(fi['fill'])
            draw.text((x, y), product_name, font=font, fill=color)
            logger.info(f"[Hybrid PIL] {sku}: product_name '{product_name}' {tw}x{th}px")

        # Ingredients
        if 'ingredients' in areas_px and ingredients:
            fi = font_info.get('ingredients', {'font_family': 'GothamMedium', 'font_size': 2.5, 'fill': '#7d277e', 'font_weight': 'normal'})
            area = areas_px['ingredients']
            font_size_px = int(fi['font_size'] * scale)

            # Try single line first
            font, tw, th = self._fit_pil_text(draw, ingredients, fi['font_family'], fi['font_weight'], font_size_px, area['width'], area['height'])
            if tw <= area['width']:
                # Single line, centered
                x = area['x'] + (area['width'] - tw) / 2
                y = area['y'] + (area['height'] - th) / 2
                color = self._hex_to_rgb(fi['fill'])
                draw.text((x, y), ingredients, font=font, fill=color)
            else:
                # Multi-line: split and draw
                lines = self._split_hybrid_text(ingredients, font_size_px, area['width'] / (0.6 * scale))
                line_font = self._get_pil_font(fi['font_family'], fi['font_weight'], font_size_px)
                line_height = font_size_px * 1.4
                total_h = line_height * len(lines)
                start_y = area['y'] + (area['height'] - total_h) / 2
                color = self._hex_to_rgb(fi['fill'])
                for i, line in enumerate(lines):
                    bbox = draw.textbbox((0, 0), line, font=line_font)
                    lw = bbox[2] - bbox[0]
                    x = area['x'] + (area['width'] - lw) / 2
                    y = start_y + i * line_height
                    draw.text((x, y), line, font=line_font, fill=color)
            logger.info(f"[Hybrid PIL] {sku}: ingredients drawn")

        # SKU
        if sku:
            fi_sku = font_info.get('sku', {'font_family': 'Arial', 'font_size': 2.5, 'fill': '#ffffff', 'font_weight': 'normal'})
            sku_text = f'SKU: {sku}  RESEARCH USE ONLY'
            font_size_sku = int(fi_sku['font_size'] * scale)
            font_sku = self._get_pil_font(fi_sku['font_family'], fi_sku['font_weight'], font_size_sku)

            # Get SKU position from garbled elements
            sku_x = 9.5 * scale
            sku_y = 49.4 * scale
            if hybrid_base['garbled_elements']:
                garbled_match = re.search(
                    r'transform="matrix\([^,]+,[^,]+,[^,]+,[^,]+,([^,]+),([^)]+)\)"',
                    hybrid_base['garbled_elements'][0]
                )
                if garbled_match:
                    sku_x = float(garbled_match.group(1)) * scale
                    sku_y = float(garbled_match.group(2)) * scale

            color_sku = self._hex_to_rgb(fi_sku['fill'])
            draw.text((sku_x, sku_y), sku_text, font=font_sku, fill=color_sku)

        # Step 4: Save outputs
        img.save(str(png_path))

        # JPG
        jpg_path = output_dir / f'label_{sku_safe}.jpg'
        try:
            img.convert('RGB').save(str(jpg_path), 'JPEG', quality=95)
        except Exception as e:
            logger.warning(f"[Hybrid PIL] JPG failed for {sku}: {e}")
            jpg_path = None

        # PDF from PNG
        pdf_path = output_dir / f'label_{sku_safe}.pdf'
        try:
            img_for_pdf = Image.open(png_path)
            img_for_pdf.save(str(pdf_path), 'PDF', resolution=300)
        except Exception as e:
            logger.warning(f"[Hybrid PIL] PDF failed for {sku}: {e}")
            pdf_path = None

        result = {'svg': str(svg_path), 'png': str(png_path)}
        if jpg_path and jpg_path.exists():
            result['jpg'] = str(jpg_path)
        if pdf_path and pdf_path.exists():
            result['pdf'] = str(pdf_path)

        logger.info(f"[Hybrid PIL] ✓ {sku}: {list(result.keys())}")
        return result

    def _calc_hybrid_font_size(self, text: str, original_size: float, max_width: float, max_height: float) -> float:
        """Calculate font size to fit text within area. Uses simple character width estimation."""
        # Approximate: average char width ≈ 0.6 * font_size for sans-serif
        char_width_ratio = 0.6
        font_size = original_size

        # Scale down if text doesn't fit width
        estimated_width = len(text) * font_size * char_width_ratio
        if estimated_width > max_width:
            font_size = max_width / (len(text) * char_width_ratio)

        # Scale down if doesn't fit height
        if font_size * 1.2 > max_height:
            font_size = max_height / 1.2

        # Don't go below minimum
        font_size = max(font_size, 1.5)
        # Don't exceed original
        font_size = min(font_size, original_size * 1.1)

        return font_size

    def _split_hybrid_text(self, text: str, font_size: float, max_width: float) -> List[str]:
        """Split text into lines that fit within max_width."""
        char_width = font_size * 0.6
        chars_per_line = int(max_width / char_width) if char_width > 0 else len(text)

        if len(text) <= chars_per_line:
            return [text]

        # Split by separator characters (/ , ;) or by word
        import re as _re
        parts = _re.split(r'\s*/\s*|\s*,\s*', text)
        parts = [p.strip() for p in parts if p.strip()]
        if len(parts) > 1:
            # Rejoin with ' / ' separator for display
            words = [parts[0]]
            for p in parts[1:]:
                words.append('/ ' + p)
        else:
            words = text.split()

        lines = []
        current_line = ''
        for word in words:
            test_line = (current_line + ' ' + word).strip() if current_line else word
            if len(test_line) * char_width <= max_width or not current_line:
                current_line = test_line
            else:
                lines.append(current_line)
                current_line = word
        if current_line:
            lines.append(current_line)

        return lines if lines else [text]

    def render_ai_to_png(self, ai_path: Path, dpi: int = 675) -> Path:
        """Render AI file to high-quality PNG for Gemini Vision OCR.

        Args:
            ai_path: Path to .ai file
            dpi: Target DPI (default 675 to match SVG conversion)

        Returns:
            Path to rendered PNG file
        """
        import fitz

        logger.info(f"Rendering AI to PNG for OCR: {ai_path} @ {dpi} DPI")

        doc = fitz.open(str(ai_path))
        page = doc[0]

        # Calculate scale matrix
        scale = dpi / 72.0
        mat = fitz.Matrix(scale, scale)

        # Render to pixmap (RGB, no alpha for smaller file)
        pix = page.get_pixmap(matrix=mat, alpha=False)

        # Save to temp PNG
        png_path = ai_path.with_suffix('.gemini_ocr.png')
        pix.save(str(png_path))

        doc.close()

        logger.info(f"✓ Rendered PNG: {png_path} ({pix.width}x{pix.height}px)")
        return png_path

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
