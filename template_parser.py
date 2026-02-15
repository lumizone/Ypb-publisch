"""Template parser for detecting and validating placeholders in vector files."""

import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from lxml import etree
import config
import logging

logger = logging.getLogger(__name__)


class TemplateParseError(Exception):
    """Raised when template parsing fails."""
    pass


class TemplateParser:
    """Parses vector templates (AI, SVG, PDF) and identifies placeholders."""
    
    def __init__(self, template_path: Path):
        self.template_path = Path(template_path)
        self.placeholder_positions: Dict[str, Dict] = {}
        self.template_type = self._detect_format()
        
        if not self.template_path.exists():
            raise TemplateParseError(f"Template file not found: {template_path}")
    
    def _detect_format(self) -> str:
        """Detect the template file format."""
        ext = self.template_path.suffix.lower()
        if ext not in config.SUPPORTED_TEMPLATE_FORMATS:
            raise TemplateParseError(
                f"Unsupported format: {ext}. Supported: {config.SUPPORTED_TEMPLATE_FORMATS}"
            )
        return ext
    
    def parse(self) -> Dict[str, Dict]:
        """Parse template and return placeholder positions."""
        if self.template_type == ".svg":
            return self._parse_svg()
        elif self.template_type == ".pdf":
            return self._parse_pdf()
        elif self.template_type == ".ai":
            # AI files are complex - assume they're exported as SVG or PDF
            # For Phase 1, we'll require SVG/PDF export
            raise TemplateParseError(
                ".AI files must be exported to SVG or PDF format first. "
                "Please export from Illustrator before uploading."
            )
        else:
            raise TemplateParseError(f"Unsupported format: {self.template_type}")
    
    def _parse_svg(self) -> Dict[str, Dict]:
        """Parse SVG file and find placeholders. Discovery only via data-placeholder."""
        try:
            tree = etree.parse(str(self.template_path))
            root = tree.getroot()
            namespaces = {'svg': 'http://www.w3.org/2000/svg', '': 'http://www.w3.org/2000/svg'}
            placeholders = {}

            # cas and mw are optional placeholders
            optional_placeholders = {'cas', 'mw'}
            for placeholder in config.REQUIRED_PLACEHOLDERS:
                candidates = root.findall(f".//*[@data-placeholder='{placeholder}']", namespaces)
                if not candidates:
                    if placeholder in optional_placeholders:
                        logger.info(f"Optional placeholder '{placeholder}' not found in template - skipping")
                        continue
                    raise TemplateParseError(
                        f"Brak elementu z data-placeholder='{placeholder}'. "
                        "Przekonwertowany plik AI musi zawierać placeholdery."
                    )
                if len(candidates) > 1:
                    logger.warning(f"Multiple elements with data-placeholder='{placeholder}', using first")
                element = candidates[0]

                aria_label = element.get('aria-label', '')
                tag_local = element.tag.split('}')[-1] if isinstance(element.tag, str) and '}' in element.tag else element.tag
                is_path_or_g = tag_local in ('path', 'g')

                if is_path_or_g and aria_label:
                    original_full_text = aria_label
                else:
                    original_full_text = ''.join(element.itertext()).strip()

                style_element = element
                if tag_local == 'g':
                    for child in element:
                        ctag = child.tag.split('}')[-1] if isinstance(child.tag, str) and '}' in child.tag else child.tag
                        if ctag in ('text', 'tspan'):
                            style_element = child
                            break

                style_info = self._get_style_info(style_element)
                x = style_element.get('x', '0')
                y = style_element.get('y', '0')
                transform = element.get('transform', '')

                placeholders[placeholder] = {
                    'element': element,
                    'x': x,
                    'y': y,
                    'font-family': style_info['font_family'],
                    'font-size': style_info['font_size'],
                    'fill': style_info['fill'],
                    'text-anchor': style_info['text_anchor'],
                    'style': style_info['style'],
                    'transform': transform,
                    'original_element': etree.tostring(element).decode(),
                    'is_aria_label': bool(aria_label),
                    'aria_label_text': aria_label,
                    'original_full_text': original_full_text,
                    'max_width': 200.0,
                }

            self.placeholder_positions = placeholders
            return placeholders

        except TemplateParseError:
            raise
        except etree.XMLSyntaxError as e:
            raise TemplateParseError(f"Invalid SVG file: {e}")
        except Exception as e:
            raise TemplateParseError(f"Error parsing SVG: {e}")
    
    def parse_by_position(self, text_areas: Dict) -> Dict[str, Dict]:
        """Parse SVG by position - find text elements whose coordinates fall within user-drawn areas.

        Used as fallback when PyMuPDF produces garbled text (custom font encoding).
        The SVG has correct positions, fonts, transforms - only text content is wrong.

        This method:
        1. Finds ALL text-like elements (<text>, <use>, <g> with aria-label)
        2. Checks which ones fall within each text_area rectangle
        3. Tags matching elements with data-placeholder attribute
        4. Saves the modified SVG
        5. Returns placeholder dict compatible with _parse_svg() output

        Args:
            text_areas: Dict of {placeholder_name: {x, y, width, height}} from user-drawn areas

        Returns:
            Same format as _parse_svg() - dict of placeholder info
        """
        try:
            tree = etree.parse(str(self.template_path))
            root = tree.getroot()
            ns = root.nsmap.get(None, 'http://www.w3.org/2000/svg')
            optional_placeholders = {'cas', 'mw'}

            # Remember existing placeholders before cleanup so we can preserve them if needed.
            existing_placeholders = {}
            for elem in root.iter():
                ph = elem.get('data-placeholder')
                if ph and ph not in existing_placeholders:
                    existing_placeholders[ph] = elem

            # Remove any existing fallback tags (clean slate)
            for elem in root.iter():
                if elem.get('data-placeholder'):
                    del elem.attrib['data-placeholder']
                if elem.get('data-placeholder-secondary'):
                    del elem.attrib['data-placeholder-secondary']

            # Collect all text-like elements with their resolved positions
            text_elements = []
            self._collect_text_elements(root, text_elements, parent_transforms=[])
            element_index = {id(te['element']): te for te in text_elements}
            assigned_ids = set()

            logger.info(f"[PositionParse] Found {len(text_elements)} text elements in SVG")

            placeholders = {}

            for placeholder_name, area in text_areas.items():
                if not area:
                    continue

                if not isinstance(area, dict):
                    logger.warning(f"[PositionParse] Invalid area for '{placeholder_name}' (expected dict), skipping")
                    continue

                if any(key not in area for key in ('x', 'y', 'width', 'height')):
                    logger.warning(f"[PositionParse] Incomplete area for '{placeholder_name}', skipping")
                    continue

                area_x = self._to_float(area.get('x'))
                area_y = self._to_float(area.get('y'))
                area_w = self._to_float(area.get('width'))
                area_h = self._to_float(area.get('height'))

                if area_w <= 0 or area_h <= 0:
                    logger.warning(f"[PositionParse] Non-positive area for '{placeholder_name}', skipping")
                    continue

                area_right = area_x + area_w
                area_bottom = area_y + area_h

                # Find elements whose position falls within this area
                matching = []
                for te in text_elements:
                    ex, ey = te['resolved_x'], te['resolved_y']
                    if area_x <= ex <= area_right and area_y <= ey <= area_bottom:
                        matching.append(te)

                if not matching:
                    # Try with expanded area (10% padding) - coordinates might be slightly off
                    pad_x = area_w * 0.1
                    pad_y = area_h * 0.1
                    for te in text_elements:
                        ex, ey = te['resolved_x'], te['resolved_y']
                        if (area_x - pad_x) <= ex <= (area_right + pad_x) and \
                           (area_y - pad_y) <= ey <= (area_bottom + pad_y):
                            matching.append(te)
                    if matching:
                        logger.info(f"[PositionParse] {placeholder_name}: found {len(matching)} elements with 10% padding")

                if not matching:
                    logger.warning(f"[PositionParse] No text elements found in area for '{placeholder_name}' "
                                 f"(area: x={area_x:.0f}, y={area_y:.0f}, w={area_w:.0f}, h={area_h:.0f})")
                    continue

                logger.info(f"[PositionParse] {placeholder_name}: {len(matching)} elements in area")

                # Use the first matching element as the "tagged" element
                # Sort by y then x to get top-left element first
                matching.sort(key=lambda e: (e['resolved_y'], e['resolved_x']))
                primary = matching[0]
                element = primary['element']
                assigned_ids.add(id(element))

                # Tag the element with data-placeholder
                element.set('data-placeholder', placeholder_name)
                if element.get('data-placeholder-secondary'):
                    del element.attrib['data-placeholder-secondary']

                # Mark other matching elements from this area so replacement can remove them.
                for secondary in matching[1:]:
                    secondary_elem = secondary['element']
                    secondary_elem.set('data-placeholder-secondary', placeholder_name)
                    assigned_ids.add(id(secondary_elem))

                # Collect original text from all matching elements (for reference)
                original_texts = []
                for m in matching:
                    t = m.get('text', '')
                    if t:
                        original_texts.append(t)
                original_full_text = ' '.join(original_texts) if original_texts else ''

                placeholders[placeholder_name] = self._build_placeholder_info(
                    element=element,
                    original_full_text=original_full_text,
                    max_width=area_w
                )
                info = placeholders[placeholder_name]
                tag_local = element.tag.split('}')[-1] if isinstance(element.tag, str) and '}' in element.tag else element.tag
                font_family = info.get('font-family', 'Arial')
                font_size = info.get('font-size', '12')

                logger.info(f"[PositionParse] Tagged '{placeholder_name}': tag={tag_local}, "
                          f"pos=({primary['resolved_x']:.1f}, {primary['resolved_y']:.1f}), "
                          f"font={font_family} {font_size}, text='{original_full_text[:40]}...'")

            # Ensure required placeholders exist. In fallback mode the UI usually marks only
            # product_name + ingredients, so we auto-resolve SKU if missing.
            missing_required = [ph for ph in config.REQUIRED_PLACEHOLDERS if ph not in placeholders and ph not in optional_placeholders]
            missing_optional = [ph for ph in config.REQUIRED_PLACEHOLDERS if ph not in placeholders and ph in optional_placeholders]
            if missing_optional:
                logger.info(f"[PositionParse] Optional placeholders not found: {missing_optional} - skipping")
            if missing_required:
                logger.warning(f"[PositionParse] Missing placeholders after area matching: {missing_required}")

            for missing_name in missing_required:
                chosen_element = None
                chosen_meta = None
                max_width = 200.0

                # 1) Reuse original tagged placeholder if present in SVG.
                if missing_name in existing_placeholders:
                    candidate = existing_placeholders[missing_name]
                    candidate_text = ''.join(candidate.itertext()).strip() or candidate.get('aria-label', '')
                    should_reuse = True
                    if missing_name == 'sku' and not self._is_likely_sku_text(candidate_text):
                        should_reuse = False

                    if should_reuse:
                        chosen_element = candidate
                        chosen_meta = element_index.get(id(candidate))
                        logger.info(f"[PositionParse] Reusing original data-placeholder='{missing_name}'")
                    else:
                        logger.info(f"[PositionParse] Ignoring stale data-placeholder='{missing_name}' candidate")

                # 2) Heuristic SKU selection for templates where user did not mark SKU area.
                if chosen_element is None and missing_name == 'sku':
                    chosen_meta = self._select_sku_candidate(text_elements, assigned_ids)
                    if chosen_meta:
                        chosen_element = chosen_meta['element']
                        logger.info(
                            f"[PositionParse] Auto-selected SKU candidate at "
                            f"({chosen_meta['resolved_x']:.1f}, {chosen_meta['resolved_y']:.1f})"
                        )

                if chosen_element is None:
                    continue

                chosen_element.set('data-placeholder', missing_name)
                assigned_ids.add(id(chosen_element))

                if missing_name == 'sku':
                    self._tag_sku_secondary_garbled(
                        text_elements=text_elements,
                        assigned_ids=assigned_ids,
                        primary_meta=chosen_meta
                    )

                original_text = ''
                if chosen_meta:
                    original_text = chosen_meta.get('text', '') or ''
                if not original_text:
                    original_text = ''.join(chosen_element.itertext()).strip() or chosen_element.get('aria-label', '')

                placeholders[missing_name] = self._build_placeholder_info(
                    element=chosen_element,
                    original_full_text=original_text,
                    max_width=max_width
                )

            # Fail fast when required placeholders are unresolved - generating with partial tags
            # produces visually broken labels (mixed old+new text).
            unresolved = [ph for ph in config.REQUIRED_PLACEHOLDERS if ph not in placeholders and ph not in optional_placeholders]
            if unresolved:
                raise TemplateParseError(
                    "Missing required placeholders after position matching: "
                    f"{', '.join(unresolved)}"
                )

            # Save modified SVG with data-placeholder tags
            tree.write(str(self.template_path), encoding='utf-8', xml_declaration=True)
            logger.info(f"[PositionParse] Saved tagged SVG: {self.template_path}")

            self.placeholder_positions = placeholders
            return placeholders

        except Exception as e:
            raise TemplateParseError(f"Position-based SVG parsing failed: {e}")

    def _collect_text_elements(self, element, results: list, parent_transforms: list):
        """Recursively collect text-like elements with their resolved global positions.

        Handles: <text>, <tspan>, <use data-text>, <g aria-label> elements.
        Resolves cumulative transforms (matrix, translate) to get global coordinates.
        """
        tag_local = element.tag.split('}')[-1] if isinstance(element.tag, str) and '}' in element.tag else element.tag

        # Build transform chain
        transform = element.get('transform', '')
        current_transforms = parent_transforms[:]
        if transform:
            current_transforms.append(transform)

        # Check if this element is a text-like element we care about
        is_text_element = False
        text_content = ''

        if tag_local == 'text':
            is_text_element = True
            text_content = ''.join(element.itertext()).strip()
        elif tag_local == 'use' and element.get('data-text'):
            is_text_element = True
            text_content = element.get('data-text', '')
        elif tag_local == 'g' and element.get('aria-label'):
            is_text_element = True
            text_content = element.get('aria-label', '')

        if is_text_element:
            # Resolve position through transform chain
            x = self._to_float(element.get('x', '0'))
            y = self._to_float(element.get('y', '0'))

            resolved_x, resolved_y = self._resolve_position(x, y, current_transforms)

            results.append({
                'element': element,
                'tag': tag_local,
                'text': text_content,
                'x': x, 'y': y,
                'resolved_x': resolved_x,
                'resolved_y': resolved_y,
                'transforms': current_transforms[:],
            })

        # Recurse into children
        for child in element:
            self._collect_text_elements(child, results, current_transforms)

    def _resolve_position(self, x: float, y: float, transforms: list) -> tuple:
        """Apply a chain of SVG transforms to resolve global position.

        Processes transforms from outermost to innermost (as they appear in DOM).
        """
        curr_x, curr_y = x, y
        for t_str in transforms:
            a, b, c, d, e, f = self._parse_transform(t_str)
            next_x = (a * curr_x) + (c * curr_y) + e
            next_y = (b * curr_x) + (d * curr_y) + f
            curr_x, curr_y = next_x, next_y

        return curr_x, curr_y

    def _parse_transform(self, transform_str: str) -> tuple:
        """Parse SVG transform and return affine matrix (a, b, c, d, e, f)."""
        a, b, c, d, e, f = 1.0, 0.0, 0.0, 1.0, 0.0, 0.0

        if not transform_str:
            return a, b, c, d, e, f

        # matrix(a, b, c, d, e, f)
        m = re.search(r'matrix\s*\(\s*([^,]+),\s*([^,]+),\s*([^,]+),\s*([^,]+),\s*([^,]+),\s*([^,\)]+)\)', transform_str)
        if m:
            a, b, c, d, e, f = [self._to_float(v) for v in m.groups()]
            return a, b, c, d, e, f

        # scale(sx, sy) or scale(s)
        m = re.search(r'scale\s*\(\s*([^,\)]+)(?:,\s*([^,\)]+))?\)', transform_str)
        if m:
            sx = self._to_float(m.group(1), 1.0)
            sy = self._to_float(m.group(2), sx) if m.group(2) else sx
            a *= sx
            d *= sy

        # translate(tx, ty)
        m = re.search(r'translate\s*\(\s*([^,\)]+)(?:,\s*([^,\)]+))?\)', transform_str)
        if m:
            e += self._to_float(m.group(1))
            f += self._to_float(m.group(2), 0.0) if m.group(2) else 0.0

        return a, b, c, d, e, f

    def _to_float(self, value, default: float = 0.0) -> float:
        """Parse numeric value from SVG attribute (supports units like '12.5px')."""
        if value is None:
            return default
        if isinstance(value, (int, float)):
            return float(value)

        text = str(value).strip()
        if not text:
            return default

        try:
            return float(text)
        except ValueError:
            match = re.search(r'[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?', text)
            if match:
                try:
                    return float(match.group(0))
                except ValueError:
                    return default
            return default

    def _build_placeholder_info(self, element, original_full_text: str, max_width: float = 200.0) -> Dict[str, Dict]:
        """Build placeholder metadata in the same format as _parse_svg()."""
        tag_local = element.tag.split('}')[-1] if isinstance(element.tag, str) and '}' in element.tag else element.tag
        aria_label = element.get('aria-label', '')

        style_element = element
        if tag_local == 'g':
            for child in element:
                ctag = child.tag.split('}')[-1] if isinstance(child.tag, str) and '}' in child.tag else child.tag
                if ctag in ('text', 'tspan', 'use'):
                    style_element = child
                    break

        style_info = self._get_style_info(style_element)
        x = style_element.get('x', '0')
        y_attr = style_element.get('y', '0')
        transform = element.get('transform', '')

        return {
            'element': element,
            'x': x,
            'y': y_attr,
            'font-family': style_info['font_family'],
            'font-size': style_info['font_size'],
            'fill': style_info['fill'],
            'text-anchor': style_info['text_anchor'],
            'style': style_info['style'],
            'transform': transform,
            'original_element': etree.tostring(element).decode(),
            'is_aria_label': bool(aria_label),
            'aria_label_text': aria_label,
            'original_full_text': original_full_text or '',
            'max_width': max_width,
        }

    def _select_sku_candidate(self, text_elements: list, assigned_ids: set):
        """Best-effort SKU element selection when SKU area is not provided by the user."""
        candidates = [te for te in text_elements if id(te['element']) not in assigned_ids]
        if not candidates:
            return None

        sku_regex = re.compile(r'YPB[.\-]?\d+', re.IGNORECASE)
        skip_keywords = (
            'FOR IM OR SQ USE ONLY',
            'NOT FOR ',
            'STORE AT ',
            'PROTECT FROM LIGHT',
            'DISTRIBUTED BY',
            'CONTACT:',
            'ADDRESS:',
            'EXPIRATION DATE',
        )

        explicit = []
        for te in candidates:
            text = (te.get('text') or '').upper()
            if sku_regex.search(text) or 'SKU' in text:
                explicit.append(te)

        if explicit:
            explicit.sort(key=lambda t: (t.get('resolved_y', 0.0), t.get('resolved_x', 0.0)), reverse=True)
            return explicit[0]

        # Fallback for garbled-text templates: choose candidate with replacement chars,
        # avoid disclaimer blocks and prefer lower-left region.
        max_x = max((te.get('resolved_x', 0.0) for te in candidates), default=1.0) or 1.0
        max_y = max((te.get('resolved_y', 0.0) for te in candidates), default=1.0) or 1.0

        def _score(te):
            text_raw = (te.get('text') or '').strip()
            text_up = text_raw.upper()
            garbled_count = text_raw.count('\ufffd')
            score = 0.0

            if garbled_count >= 2:
                score += 60.0
            if any(key in text_up for key in skip_keywords):
                score -= 100.0

            y_norm = float(te.get('resolved_y', 0.0)) / max_y
            x_norm = float(te.get('resolved_x', 0.0)) / max_x
            score += y_norm * 20.0
            score += (1.0 - x_norm) * 12.0

            if 4 <= len(text_raw) <= 40:
                score += 4.0
            return score

        ranked = sorted(candidates, key=_score, reverse=True)
        if not ranked:
            return None

        best = ranked[0]
        best_text = (best.get('text') or '').upper()
        if '\ufffd' not in best_text and not sku_regex.search(best_text):
            return None
        return best

    def _is_likely_sku_text(self, text: str) -> bool:
        """Check if text looks like SKU field content and not disclaimer copy."""
        if not text:
            return False

        normalized = text.upper()
        if re.search(r'YPB[.\-]?\d+', normalized):
            return True
        if 'SKU' in normalized:
            return True
        if text.count('\ufffd') >= 2:
            return True

        disallowed = (
            'FOR IM OR SQ USE ONLY',
            'NOT FOR ',
            'STORE AT ',
            'PROTECT FROM LIGHT',
            'DISTRIBUTED BY',
            'CONTACT:',
            'ADDRESS:',
        )
        return not any(token in normalized for token in disallowed)

    def _tag_sku_secondary_garbled(self, text_elements: list, assigned_ids: set, primary_meta: Optional[Dict]):
        """Mark nearby garbled lines as SKU secondary so replacer can remove them."""
        if not primary_meta:
            return

        primary_elem = primary_meta.get('element')
        primary_y = float(primary_meta.get('resolved_y', 0.0))
        primary_x = float(primary_meta.get('resolved_x', 0.0))

        marked = 0
        for te in text_elements:
            elem = te.get('element')
            if elem is None or elem is primary_elem or id(elem) in assigned_ids:
                continue

            text = te.get('text') or ''
            if text.count('\ufffd') < 2:
                continue

            y = float(te.get('resolved_y', 0.0))
            x = float(te.get('resolved_x', 0.0))
            if abs(y - primary_y) > 55.0:
                continue

            # Keep only lines that look like the same small block as the SKU line.
            if abs(x - primary_x) > 220.0:
                continue

            elem.set('data-placeholder-secondary', 'sku')
            assigned_ids.add(id(elem))
            marked += 1

        if marked:
            logger.info(f"[PositionParse] Marked {marked} nearby garbled SKU secondary elements")

    def _get_style_info(self, style_element) -> Dict[str, str]:
        """Extract style consistently from inline CSS and direct SVG attributes."""
        style = (style_element.get('style') or '').strip()

        font_family = style_element.get('font-family') or self._extract_style(style, 'font-family', 'Arial')
        font_size = style_element.get('font-size') or self._extract_style(style, 'font-size', '12')
        fill = style_element.get('fill') or self._extract_style(style, 'fill', '#000000')
        text_anchor = style_element.get('text-anchor') or self._extract_style(style, 'text-anchor', 'start')
        font_weight = style_element.get('font-weight') or self._extract_style(style, 'font-weight', 'normal')
        font_style = style_element.get('font-style') or self._extract_style(style, 'font-style', 'normal')

        if not style:
            style = (
                f"font-family:{font_family};"
                f"font-size:{font_size};"
                f"fill:{fill};"
                f"font-weight:{font_weight};"
                f"font-style:{font_style};"
            )

        return {
            'style': style,
            'font_family': font_family,
            'font_size': font_size,
            'fill': fill,
            'text_anchor': text_anchor,
        }

    def _parse_pdf(self) -> Dict[str, Dict]:
        """Parse PDF file and find placeholders."""
        # PDF parsing is more complex - for Phase 1, we recommend SVG
        # This is a placeholder that would need pdfrw or similar
        raise TemplateParseError(
            "PDF template parsing not yet implemented. "
            "Please export your Illustrator file as SVG for Phase 1."
        )
    
    def _extract_style(self, style_string: str, property_name: str, default: str) -> str:
        """Extract a CSS property from style string."""
        if not style_string:
            return default
        
        pattern = rf"{property_name}:\s*([^;]+)"
        match = re.search(pattern, style_string)
        return match.group(1).strip().strip("'\"") if match else default
    
    def validate(self) -> Tuple[bool, List[str]]:
        """Validate template has all required placeholders."""
        try:
            self.parse()
            return True, []
        except TemplateParseError as e:
            return False, [str(e)]
