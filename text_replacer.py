"""Text replacement engine that preserves all styling and layout."""

from pathlib import Path
from typing import Dict
from lxml import etree
import re
import logging
import config
from template_parser import TemplateParser
from text_formatter import TextFormatter

logger = logging.getLogger(__name__)


class TextReplacerError(Exception):
    """Raised when text replacement fails."""
    pass


class TextReplacer:
    """Replaces placeholder text while preserving all styling and layout."""
    
    # Mapping from placeholder names to possible CSV column names
    FIELD_MAPPING = {
        'sku': ['SKU', 'sku'],
        'product_name': ['Product', 'product_name', 'Name', 'name'],
        'ingredients': ['Ingredients', 'ingredients', 'Composition', 'composition', 'Dosage', 'dosage'],
        'cas': ['CAS', 'cas', 'CAS Number', 'cas_number'],
        'mw': ['MW', 'mw', 'M.W.', 'M.W', 'Molecular Weight', 'molecular_weight'],
    }

    def __init__(self, template_parser: TemplateParser, text_areas: Dict = None, text_alignments: Dict = None):
        self.parser = template_parser
        self.template_path = template_parser.template_path
        self.formatter = TextFormatter()
        self.text_areas = text_areas or {}  # User-defined text areas: {placeholder_name: {x, y, width, height}}
        self.text_alignments = text_alignments or {}  # User-defined text alignments: {placeholder_name: 'left'|'center'|'right'}

    def _get_text_anchor(self, placeholder_name: str) -> str:
        """Get SVG text-anchor value based on user-selected alignment."""
        alignment = self.text_alignments.get(placeholder_name, 'left')
        # Map alignment to SVG text-anchor values
        anchor_map = {
            'left': 'start',
            'center': 'middle',
            'right': 'end'
        }
        return anchor_map.get(alignment, 'start')

    def _get_product_value(self, product_data: Dict[str, str], placeholder_name: str) -> str:
        """Get product value supporting both uppercase and lowercase field names."""
        # Try direct match first
        if placeholder_name in product_data:
            return product_data[placeholder_name]

        # Try mapped field names
        possible_names = self.FIELD_MAPPING.get(placeholder_name, [placeholder_name])
        for name in possible_names:
            if name in product_data and product_data[name]:
                return product_data[name]

        return ''
    
    def replace(self, product_data: Dict[str, str]) -> Path:
        """Replace placeholders in template with product data."""
        try:
            # Parse template to get placeholder positions
            placeholders = self.parser.parse()

            # Load SVG
            tree = etree.parse(str(self.template_path))
            root = tree.getroot()

            # Register namespaces
            namespaces = {'': 'http://www.w3.org/2000/svg'}

            # Pre-calculate synchronized CAS/MW formatting
            self._cas_mw_format = self._sync_cas_mw_format(placeholders, product_data, root)

            # Replace each placeholder
            for placeholder_name, placeholder_info in placeholders.items():
                # Support both uppercase (CSV) and lowercase (DataMapper) field names
                value = self._get_product_value(product_data, placeholder_name)
                if not value:
                    if placeholder_name in ('cas', 'mw'):
                        logger.info(f"Optional placeholder '{placeholder_name}' has no value - skipping")
                        continue
                    raise TextReplacerError(
                        f"Missing value for placeholder: {placeholder_name}"
                    )
                
                # Find the element again (in case structure changed)
                element = self._find_element(root, placeholder_name, placeholder_info)
                
                if element is None:
                    raise TextReplacerError(
                        f"Could not find element for placeholder: {placeholder_name}"
                    )
                
                # Check if user_area is defined - only move elements with user_area
                # Elements WITHOUT user_area should stay in place (transform applies correctly)
                user_area = self.text_areas.get(placeholder_name)
                if user_area:
                    # Move to root level because user_area coordinates are in global SVG space
                    element = self._move_element_to_root(root, element, placeholder_name, apply_transform=False)
                
                # Replace text content while preserving structure
                placeholder_info['placeholder_name'] = placeholder_name
                self._replace_text_content(element, value, placeholder_info)
            
            # Save modified SVG
            sku_value = self._get_product_value(product_data, 'sku') or 'temp'
            output_path = config.TEMP_DIR / f"label_{sku_value}.svg"
            tree.write(str(output_path), encoding='utf-8', xml_declaration=True)
            
            return output_path
            
        except Exception as e:
            raise TextReplacerError(f"Text replacement failed: {e}")
    
    def _find_element(self, root, placeholder_name: str, placeholder_info: Dict):
        """Find the element corresponding to a placeholder. Only via data-placeholder."""
        candidates = root.findall(f".//*[@data-placeholder='{placeholder_name}']")
        if not candidates:
            return None
        if len(candidates) > 1:
            logger.warning(f"Multiple elements with data-placeholder='{placeholder_name}', using first")
        return candidates[0]

    _SKU_REGEX = re.compile(r'YPB[.\-]\d+', re.IGNORECASE)
    _SKU_RUO_SPACE = re.compile(r'(YPB[.\-]\d+)(RESEARCH\s+USE\s+ONLY)', re.IGNORECASE)

    def _sync_cas_mw_format(self, placeholders, product_data, root):
        """Pre-calculate synchronized font size and line count for CAS and MW.

        Automatically detects available zone by scanning neighboring text elements:
        - Top boundary = nearest text element ABOVE CAS (+ padding)
        - Bottom boundary = nearest text element BELOW MW (- padding)
        - Right boundary = SVG width - padding

        Both CAS and MW always use the same font size and same number of lines.
        """
        cas_info = placeholders.get('cas')
        mw_info = placeholders.get('mw')
        if not cas_info and not mw_info:
            return None

        # Build display values with prefix
        cas_value = self._get_product_value(product_data, 'cas') if cas_info else ''
        mw_value = self._get_product_value(product_data, 'mw') if mw_info else ''

        def _build_display(ph_info, value):
            if not ph_info or not value:
                return ''
            orig = ph_info.get('original_full_text', '')
            if orig and ':' in orig:
                prefix = orig.split(':', 1)[0] + ': '
                return prefix + value
            return value

        cas_display = _build_display(cas_info, cas_value)
        mw_display = _build_display(mw_info, mw_value)

        # Get font info
        ref_info = cas_info or mw_info
        font_family = ref_info.get('font-family', 'Arial') or 'Arial'
        orig_font_size = float(ref_info.get('font-size', '23').replace('px', ''))

        # --- Get SVG dimensions ---
        svg_width = 1181.0
        svg_height = 506.0
        vb = root.get('viewBox', '')
        if vb:
            parts = vb.split()
            if len(parts) >= 3:
                svg_width = float(parts[2])
            if len(parts) >= 4:
                svg_height = float(parts[3])

        # --- Find CAS/MW element positions ---
        ns_svg = 'http://www.w3.org/2000/svg'
        cas_y = None
        mw_y = None
        elem_x = 619.0

        for ph_name, store in [('cas', 'cas_y'), ('mw', 'mw_y')]:
            for selector in [f".//*[@data-placeholder='{ph_name}']",
                             f".//{{{ns_svg}}}*[@data-placeholder='{ph_name}']"]:
                elems = root.findall(selector)
                if elems:
                    y_val = elems[0].get('y', '')
                    x_val = elems[0].get('x', '')
                    if y_val:
                        if store == 'cas_y':
                            cas_y = float(y_val)
                        else:
                            mw_y = float(y_val)
                    if x_val:
                        elem_x = float(x_val)
                    break

        if cas_y is None and mw_y is None:
            return None

        # --- Collect positions of ALL text elements in same X region ---
        # Store (y, font_size) tuples for proper boundary calculation
        neighbor_elements = []  # (y, font_size)
        for elem in root.iter():
            tag = elem.tag.split('}')[-1] if isinstance(elem.tag, str) and '}' in elem.tag else elem.tag
            if tag != 'text':
                continue
            x_str = elem.get('x', '')
            y_str = elem.get('y', '')
            ph = elem.get('data-placeholder', '')
            if not y_str:
                continue
            try:
                ey = float(y_str)
                ex = float(x_str) if x_str else 0
            except ValueError:
                continue
            # Only consider elements in the same horizontal region (right side of label)
            if ex >= elem_x - 50 and ph not in ('cas', 'mw'):
                elem_fs_str = elem.get('font-size', '') or ''
                elem_fs = float(elem_fs_str.replace('px', '')) if elem_fs_str else orig_font_size
                neighbor_elements.append((ey, elem_fs))

        # --- Find boundaries ---
        top_y = cas_y if cas_y else (mw_y - 45)  # CAS position or estimate
        bottom_y = mw_y if mw_y else (cas_y + 45)  # MW position or estimate

        # Find nearest element ABOVE CAS (its baseline + font_size = its bottom)
        above = [(y, fs) for y, fs in neighbor_elements if y < top_y]
        if above:
            nearest_above = max(above, key=lambda t: t[0])
            boundary_top = nearest_above[0] + 5  # baseline of above + small gap
        else:
            boundary_top = top_y - 10

        # Find nearest element BELOW MW
        # SVG y = baseline, visual top of text = y - font_size * 0.8 (ascender)
        below = [(y, fs) for y, fs in neighbor_elements if y > bottom_y]
        if below:
            nearest_below = min(below, key=lambda t: t[0])
            # Visual top of below text = baseline - ascender height
            boundary_bottom = nearest_below[0] - nearest_below[1] * 0.85 - 3
        else:
            boundary_bottom = svg_height - 10

        available_height = boundary_bottom - boundary_top

        # Right boundary = label edge (SVG width) with padding
        right_padding = 15
        available_width = svg_width - elem_x - right_padding
        vertical_gap = 8  # min gap between CAS and MW

        logger.info(f"[CAS/MW zone] top={boundary_top:.0f}, bottom={boundary_bottom:.0f}, "
                    f"height={available_height:.0f}px, width={available_width:.0f}px, "
                    f"svg_w={svg_width:.0f}, elem_x={elem_x:.0f}, "
                    f"orig_cas_y={cas_y}, orig_mw_y={mw_y}, "
                    f"neighbors_above={len(above)}, neighbors_below={len(below)}")

        # --- Calculate font size and line count to fit in width ---
        texts = [t for t in [cas_display, mw_display] if t]
        if not texts:
            return None
        longest = max(texts, key=len)

        font_size = orig_font_size
        num_lines = 1  # per field

        # Measure each text individually to decide
        widths = {}
        for t in texts:
            w = self.formatter.measure_text_width(t, font_family, font_size)
            widths[t] = w
        longest = max(texts, key=lambda t: widths[t])
        text_width = widths[longest]

        logger.info(f"[CAS/MW measure] longest='{longest[:50]}', "
                    f"measured_w={text_width:.0f}px, available_w={available_width:.0f}px, "
                    f"font={font_size:.1f}px, fits={text_width <= available_width}")

        # Step 1: try 1 line at original font size
        if text_width <= available_width:
            pass  # fits
        else:
            # Step 2: shrink font up to 20% trying to keep 1 line
            while font_size > orig_font_size * 0.8:
                font_size *= 0.95
                text_width = self.formatter.measure_text_width(longest, font_family, font_size)
                if text_width <= available_width:
                    break

            if text_width > available_width:
                # Step 3: wrap to 2 lines at 90% of original size
                num_lines = 2
                font_size = orig_font_size * 0.9
                # Check width of half-text (approximate wrapped line)
                half_text = longest[:len(longest) // 2 + 1]
                half_w = self.formatter.measure_text_width(half_text, font_family, font_size)
                while half_w > available_width and font_size > orig_font_size * 0.6:
                    font_size *= 0.95
                    half_w = self.formatter.measure_text_width(half_text, font_family, font_size)

        # Line height - tight spacing for multi-line
        line_height = font_size * 1.1

        # Keep ORIGINAL Y positions - CAS and MW stay where they are in the template
        cas_new_y = cas_y  # keep original position
        mw_new_y = mw_y    # keep original position

        if num_lines >= 2 and cas_y is not None and mw_y is not None:
            # CAS wraps to 2 lines - push MW down by the extra line
            extra_line = line_height * (num_lines - 1)
            cas_block_bottom = cas_y + extra_line
            if mw_y < cas_block_bottom + vertical_gap:
                mw_new_y = cas_block_bottom + vertical_gap

        # Also check if MW wraps and would overflow bottom boundary
        if num_lines >= 2 and mw_new_y is not None:
            mw_block_bottom = mw_new_y + line_height * (num_lines - 1)
            if mw_block_bottom > boundary_bottom:
                # Shrink further to fit
                font_size *= 0.9
                line_height = font_size * 1.1

        logger.info(f"[CAS/MW sync] font={font_size:.1f}px (orig={orig_font_size:.1f}px), "
                    f"lines={num_lines}, line_h={line_height:.1f}, "
                    f"cas_y={cas_new_y}, mw_y={mw_new_y}, "
                    f"available_w={available_width:.0f}px")

        return {
            'font_size': font_size,
            'num_lines': num_lines,
            'available_width': available_width,
            'font_family': font_family,
            'orig_font_size': orig_font_size,
            'cas_y': cas_new_y,
            'mw_y': mw_new_y,
            'line_height': line_height,
        }

    def _surgical_sku_display_text(self, original_full_text: str, new_sku: str) -> str:
        """Replace only the SKU value (e.g. YPB.100) in original text, keep prefix/suffix.
        Ensures a space between SKU and 'RESEARCH USE ONLY' (Inkscape often exports without it)."""
        m = self._SKU_REGEX.search(original_full_text)
        if m:
            old_sku = m.group(0)
            result = original_full_text.replace(old_sku, new_sku, 1)
            # Normalize: always insert space between YPB.xxx and "RESEARCH USE ONLY"
            result = self._SKU_RUO_SPACE.sub(r'\1 \2', result)
            return result
        return new_sku

    def _replace_text_content(self, element, new_text: str, placeholder_info: Dict):
        """Replace text content while preserving all formatting and intelligently formatting text."""
        placeholder_name = placeholder_info.get('placeholder_name', '')

        # Get local tag name
        tag = element.tag
        if isinstance(tag, str) and '}' in tag:
            tag_local = tag.split('}')[-1]
        else:
            tag_local = tag

        # Check if this is an aria-label element (text converted to paths)
        aria_label = element.get('aria-label', '')
        is_path_or_g_with_aria = aria_label and tag_local in ('path', 'g')

        if is_path_or_g_with_aria:
            logger.info(f"{placeholder_name}: element is {tag_local} with aria-label, converting to text element")
            return self._replace_aria_label_element(element, new_text, placeholder_info)

        # If element is a group (<g>), find the first text element and remove others
        if element.tag.endswith('g') or element.tag.endswith('{http://www.w3.org/2000/svg}g'):
            logger.info(f"{placeholder_name}: element is a group, finding text children")
            text_children = [child for child in element if child.tag.endswith('text') or child.tag.endswith('{http://www.w3.org/2000/svg}text')]
            if text_children:
                # Use first text element as base
                base_text = text_children[0]
                # Remove all other text elements from group
                for text_child in text_children[1:]:
                    element.remove(text_child)
                    logger.info(f"{placeholder_name}: removed extra text element from group")
                # Replace element reference with the base text element
                element = base_text
            else:
                # Check if group has path children with aria-label (text-to-path conversion)
                path_children = [child for child in element if child.tag.endswith('path') or child.tag.endswith('{http://www.w3.org/2000/svg}path')]
                if path_children and aria_label:
                    logger.info(f"{placeholder_name}: group has path children, converting to text")
                    return self._replace_aria_label_element(element, new_text, placeholder_info)
                logger.warning(f"{placeholder_name}: group has no text children!")
                return

        # Check if user-defined area exists for this placeholder
        user_area = self.text_areas.get(placeholder_name)

        # Display value: surgical SKU replace (only YPB.xxx) vs full replace for name/ingredients/cas/mw
        if placeholder_name == 'sku':
            orig = placeholder_info.get('original_full_text', '')
            display_value = self._surgical_sku_display_text(orig, new_text)
        # CAS and MW: surgical replace - keep prefix (e.g. "CAS: " / "M.W.: ")
        elif placeholder_name in ('cas', 'mw'):
            orig = placeholder_info.get('original_full_text', '')
            # Find the old value in original text and replace only that part
            old_value = None
            for key in self.FIELD_MAPPING.get(placeholder_name, []):
                # Try to find old value by checking what product data was in template
                pass
            # If original has a prefix like "CAS: xxx" or "M.W.: xxx", keep the prefix
            if orig and ':' in orig:
                prefix = orig.split(':', 1)[0] + ': '
                display_value = prefix + new_text
            else:
                display_value = new_text
        else:
            display_value = new_text

        # Remove additional elements from the same detected placeholder area.
        # This is required for fallback templates where one logical field spans
        # multiple original text nodes.
        self._remove_secondary_area_elements(element, placeholder_name)

        # For elements WITHOUT user_area - replace text, preserve position/style
        if not user_area:
            # CAS/MW: use pre-calculated synchronized format with zone-aware positioning
            if placeholder_name in ('cas', 'mw') and self._cas_mw_format:
                fmt = self._cas_mw_format
                font_size = fmt['font_size']
                num_lines = fmt['num_lines']
                line_height = fmt['line_height']

                # Split text into lines if needed
                lines = [display_value]
                if num_lines >= 2:
                    mid = len(display_value) // 2
                    best_pos = -1
                    for offset in range(mid):
                        if mid + offset < len(display_value) and display_value[mid + offset] == ' ':
                            best_pos = mid + offset
                            break
                        if mid - offset >= 0 and display_value[mid - offset] == ' ':
                            best_pos = mid - offset
                            break
                    if best_pos > 0:
                        lines = [display_value[:best_pos].strip(), display_value[best_pos:].strip()]
                        lines = [l for l in lines if l]

                # Set Y position from zone calculation
                new_y = fmt.get('cas_y') if placeholder_name == 'cas' else fmt.get('mw_y')
                if new_y is not None:
                    element.set('y', f'{new_y:.2f}')

                logger.info(f"{placeholder_name}: synced {len(lines)} line(s), font={font_size:.1f}px, "
                            f"y={new_y:.1f}, text='{display_value[:40]}'")

                # Get SVG namespace
                ns = '{http://www.w3.org/2000/svg}'
                if element.tag.startswith('{'):
                    ns = element.tag.rsplit('}', 1)[0] + '}'

                element.set('font-size', f'{font_size:.2f}px')

                # Clear existing content
                for child in list(element):
                    element.remove(child)
                element.text = None

                if len(lines) == 1:
                    element.text = lines[0]
                else:
                    x_pos = element.get('x', '0')
                    for i, line in enumerate(lines):
                        tspan = etree.SubElement(element, f'{ns}tspan')
                        tspan.text = line
                        tspan.set('x', x_pos)
                        if i > 0:
                            tspan.set('dy', f'{line_height:.1f}')
                return

            logger.info(f"{placeholder_name}: no user_area, preserving position/style, replacing with: {display_value[:50]}...")
            tspans = list(element)
            if tspans:
                for child in tspans:
                    tag_name = child.tag.split('}')[-1] if '}' in child.tag else child.tag
                    if tag_name == 'tspan':
                        child.text = display_value
                        logger.info(f"{placeholder_name}: replaced tspan with display value")
                        break
                else:
                    for child in reversed(tspans):
                        tag_name = child.tag.split('}')[-1] if '}' in child.tag else child.tag
                        if tag_name == 'tspan':
                            child.text = display_value
                            break
            else:
                element.text = display_value
            return

        # FROM HERE: only for elements WITH user_area
        area_x = float(user_area['x'])
        area_y = float(user_area['y'])
        area_width = float(user_area['width'])
        area_height = float(user_area['height'])
        font_family = placeholder_info.get('font-family', 'Arial') or 'Arial'

        # Use TextFormatter to find optimal layout - it handles all the fitting logic
        formatted = self.formatter.format_text(
            text=display_value,
            placeholder_info=placeholder_info,
            max_width=area_width,
            max_height=area_height,
            placeholder_name=placeholder_name,
        )
        lines = formatted['lines']
        optimal_font_size = float(formatted['font_size'])
        line_height = formatted.get('line_height', optimal_font_size * 1.2)

        needs_wrap = len(lines) > 1

        # VALIDATE: Final check that text fits within the area - ENFORCE HARD LIMIT
        total_text_height = line_height * len(lines)
        max_line_width = max(self.formatter.measure_text_width(line, font_family, optimal_font_size) for line in lines) if lines else 0

        # If text exceeds area, REDUCE font size until it fits (Railway has different font metrics!)
        safety_margin = 1.05  # 5% margin for font rendering differences
        retry_count = 0
        max_retries = 20

        while (max_line_width * safety_margin > area_width or total_text_height > area_height) and retry_count < max_retries:
            retry_count += 1
            # Reduce font size by 5%
            optimal_font_size *= 0.95
            line_height = optimal_font_size * 1.2

            # Recalculate with smaller font
            total_text_height = line_height * len(lines)
            max_line_width = max(self.formatter.measure_text_width(line, font_family, optimal_font_size) for line in lines) if lines else 0

            logger.info(f"{placeholder_name}: Reducing font to {optimal_font_size:.1f}px (retry {retry_count}) - width={max_line_width:.0f}, height={total_text_height:.0f}")

        if max_line_width * safety_margin > area_width or total_text_height > area_height:
            logger.error(f"CRITICAL: {placeholder_name} text STILL exceeds area after {max_retries} retries!")
            logger.error(f"  Text size: {max_line_width:.0f}x{total_text_height:.0f}, Area: {area_width:.0f}x{area_height:.0f}")
        else:
            logger.info(f"Formatted '{placeholder_name}': {len(lines)} lines, font={optimal_font_size:.1f}px, "
                        f"text_size={max_line_width:.0f}x{total_text_height:.0f}, area={area_width:.0f}x{area_height:.0f} ✓")

        # Clear existing text nodes
        for child in list(element):
            element.remove(child)
        element.text = None

        # Get SVG namespace
        ns = '{http://www.w3.org/2000/svg}'
        if element.tag.startswith('{'):
            ns = element.tag.rsplit('}', 1)[0] + '}'

        logger.info(f"Using user-defined area for {placeholder_name}: x={area_x:.1f}, y={area_y:.1f}, w={area_width:.1f}, h={area_height:.1f}")

        # Get text alignment
        text_anchor = self._get_text_anchor(placeholder_name)

        # Calculate X position based on alignment
        if text_anchor == 'start':  # left
            x_pos = area_x
        elif text_anchor == 'end':  # right
            x_pos = area_x + area_width
        else:  # middle (center)
            x_pos = area_x + (area_width / 2)

        # Calculate Y position
        total_height = line_height * len(lines)
        if needs_wrap and len(lines) > 1:
            # Multi-line: vertically centered
            padding = max(0, (area_height - total_height) / 2)
            y_pos = area_y + padding + (optimal_font_size * 0.85)
        else:
            # Single line: vertically centered
            center_y = area_y + (area_height / 2)
            y_pos = center_y + (optimal_font_size * 0.35)

        # Update element position and style
        element.set('x', str(x_pos))
        element.set('y', str(y_pos))
        element.set('text-anchor', text_anchor)

        # Update font size in style
        style = element.get('style', '')
        if style:
            if re.search(r'font-size:\s*[\d.]+px', style):
                style = re.sub(r'font-size:\s*[\d.]+px', f'font-size:{optimal_font_size:.2f}px', style)
            else:
                style = f'font-size:{optimal_font_size:.2f}px;' + style
            element.set('style', style)
        else:
            element.set('style', f'font-size:{optimal_font_size:.2f}px;')

        # Handle multi-line text with tspan
        if needs_wrap and len(lines) > 1:
            for i, line_text in enumerate(lines):
                tspan = etree.SubElement(element, ns + 'tspan')
                tspan.set('x', str(x_pos))
                tspan.set('text-anchor', text_anchor)
                tspan.set('dy', '0' if i == 0 else f'{line_height:.1f}')
                tspan.text = line_text
            logger.info(f"Created {len(lines)} tspans for multi-line text")
        else:
            # Single line text
            element.text = lines[0] if lines else display_value

    def _remove_secondary_area_elements(self, primary_element, placeholder_name: str):
        """Remove extra elements tagged for the same placeholder area."""
        try:
            root = primary_element.getroottree().getroot()
            secondary_xpath = f".//*[@data-placeholder-secondary='{placeholder_name}']"
            secondary_elements = root.findall(secondary_xpath)
            if not secondary_elements:
                return

            parent_map = {c: p for p in root.iter() for c in p}
            removed = 0
            for secondary in secondary_elements:
                if secondary is primary_element:
                    continue
                parent = parent_map.get(secondary)
                if parent is None:
                    continue
                parent.remove(secondary)
                removed += 1

            if removed:
                logger.info(f"{placeholder_name}: removed {removed} secondary text elements from same area")
        except Exception as e:
            logger.warning(f"{placeholder_name}: failed to remove secondary elements: {e}")
    
    def _parse_transform_matrix(self, transform_str: str):
        """Parse SVG transform attribute and return scale and translate values."""
        # Default: no transform (identity)
        scale_x, scale_y = 1.0, 1.0
        translate_x, translate_y = 0.0, 0.0
        
        if not transform_str:
            return scale_x, scale_y, translate_x, translate_y
        
        # Parse matrix(a, b, c, d, e, f) - a=scaleX, d=scaleY, e=translateX, f=translateY
        matrix_match = re.search(r'matrix\s*\(\s*([^,]+),\s*([^,]+),\s*([^,]+),\s*([^,]+),\s*([^,]+),\s*([^,\)]+)\)', transform_str)
        if matrix_match:
            a, b, c, d, e, f = [float(x) for x in matrix_match.groups()]
            scale_x = a
            scale_y = d
            translate_x = e
            translate_y = f
            return scale_x, scale_y, translate_x, translate_y
        
        # Parse scale(sx, sy) or scale(s)
        scale_match = re.search(r'scale\s*\(\s*([^,\)]+)(?:,\s*([^,\)]+))?\)', transform_str)
        if scale_match:
            scale_x = float(scale_match.group(1))
            scale_y = float(scale_match.group(2)) if scale_match.group(2) else scale_x
        
        # Parse translate(tx, ty) or translate(tx)
        translate_match = re.search(r'translate\s*\(\s*([^,\)]+)(?:,\s*([^,\)]+))?\)', transform_str)
        if translate_match:
            translate_x = float(translate_match.group(1))
            translate_y = float(translate_match.group(2)) if translate_match.group(2) else 0.0
        
        return scale_x, scale_y, translate_x, translate_y
    
    def _move_element_to_root(self, root, element, placeholder_name: str, apply_transform: bool = False):
        """Move text element to root level (outside any transform groups).
        
        If apply_transform is True, the element's position and font-size will be adjusted
        to account for the transform being removed (for elements without user_area).
        """
        # Find parent of this element
        parent_map = {c: p for p in root.iter() for c in p}
        parent = parent_map.get(element)
        
        if parent is None:
            logger.info(f"{placeholder_name}: element has no parent, already at root")
            return element  # Already at root
        
        # Check if any ancestor has a transform attribute and collect all transforms
        transforms = []
        current = parent
        while current is not None:
            transform_val = current.get('transform')
            if transform_val:
                transforms.append(transform_val)
                logger.info(f"{placeholder_name}: found transform in ancestor: {transform_val[:50]}...")
            current = parent_map.get(current)
        
        if not transforms:
            logger.info(f"{placeholder_name}: no transform in ancestry, keeping in place")
            return element  # No transform in ancestry, keep in place
        
        logger.info(f"Moving {placeholder_name} text element to root level (was inside transformed group)")
        
        # Calculate cumulative transform (multiply all transforms)
        cumulative_scale_x, cumulative_scale_y = 1.0, 1.0
        cumulative_translate_x, cumulative_translate_y = 0.0, 0.0
        
        for transform_str in transforms:
            sx, sy, tx, ty = self._parse_transform_matrix(transform_str)
            # Apply transform: new_point = scale * old_point + translate
            # For multiple transforms: work from innermost to outermost
            cumulative_translate_x = cumulative_translate_x * sx + tx
            cumulative_translate_y = cumulative_translate_y * sy + ty
            cumulative_scale_x *= sx
            cumulative_scale_y *= sy
        
        logger.info(f"{placeholder_name}: cumulative transform - scale=({cumulative_scale_x:.3f}, {cumulative_scale_y:.3f}), translate=({cumulative_translate_x:.1f}, {cumulative_translate_y:.1f})")
        
        # Apply transform to element's position and font-size if needed
        if apply_transform and cumulative_scale_x != 1.0:
            # Get current position
            x = element.get('x')
            y = element.get('y')
            if x:
                try:
                    new_x = float(x) * cumulative_scale_x + cumulative_translate_x
                    element.set('x', str(new_x))
                    logger.info(f"{placeholder_name}: transformed x: {x} -> {new_x:.2f}")
                except ValueError:
                    pass
            if y:
                try:
                    new_y = float(y) * cumulative_scale_y + cumulative_translate_y
                    element.set('y', str(new_y))
                    logger.info(f"{placeholder_name}: transformed y: {y} -> {new_y:.2f}")
                except ValueError:
                    pass
            
            # Scale font-size
            style = element.get('style', '')
            if 'font-size' in style:
                fs_match = re.search(r'font-size:\s*([\d.]+)(px|pt|em|%)?', style)
                if fs_match:
                    old_size = float(fs_match.group(1))
                    unit = fs_match.group(2) or 'px'
                    new_size = old_size * cumulative_scale_x  # Use scale_x for font-size
                    new_style = re.sub(r'font-size:\s*[\d.]+(?:px|pt|em|%)?', f'font-size:{new_size:.2f}{unit}', style)
                    element.set('style', new_style)
                    logger.info(f"{placeholder_name}: scaled font-size: {old_size} -> {new_size:.2f}")
            
            # Also check for font-size attribute directly
            font_size_attr = element.get('font-size')
            if font_size_attr:
                try:
                    fs_match = re.match(r'([\d.]+)(px|pt|em|%)?', font_size_attr)
                    if fs_match:
                        old_size = float(fs_match.group(1))
                        unit = fs_match.group(2) or ''
                        new_size = old_size * cumulative_scale_x
                        element.set('font-size', f'{new_size:.2f}{unit}')
                        logger.info(f"{placeholder_name}: scaled font-size attr: {old_size} -> {new_size:.2f}")
                except ValueError:
                    pass
        
        # Remove from parent
        parent.remove(element)
        
        # Find the main layer group - look for a <g> that is direct child of root or first <g> in SVG
        # and doesn't have a transform
        main_layer = None
        for child in root:
            tag_name = child.tag.split('}')[-1] if '}' in child.tag else child.tag
            if tag_name == 'g' and not child.get('transform'):
                main_layer = child
                logger.info(f"Found main layer group without transform")
                break
        
        # If no suitable group found, add directly to root
        if main_layer is not None:
            main_layer.append(element)
            logger.info(f"Added {placeholder_name} to main layer")
        else:
            root.append(element)
            logger.info(f"Added {placeholder_name} to root")
        
        return element
    
    def replace_in_svg_string(self, svg_content: str, product_data: Dict[str, str]) -> str:
        """Replace placeholders in SVG string content."""
        # Parse placeholders first
        placeholders = self.parser.parse()

        # Parse SVG
        root = etree.fromstring(svg_content.encode('utf-8'))

        # Replace each placeholder
        for placeholder_name, placeholder_info in placeholders.items():
            value = self._get_product_value(product_data, placeholder_name)
            
            element = self._find_element(root, placeholder_name, placeholder_info)
            if element is not None:
                # Check if user_area is defined - only move elements with user_area
                # Elements WITHOUT user_area should stay in place (transform applies correctly)
                user_area = self.text_areas.get(placeholder_name)
                if user_area:
                    # Move to root level because user_area coordinates are in global SVG space
                    element = self._move_element_to_root(root, element, placeholder_name, apply_transform=False)
                
                placeholder_info['placeholder_name'] = placeholder_name
                self._replace_text_content(element, value, placeholder_info)
        
        return etree.tostring(root, encoding='unicode')
    
    def _replace_aria_label_element(self, element, new_text: str, placeholder_info: Dict):
        """Replace text in an aria-label element (path/g with text converted to paths).

        This creates a new <text> element with the replacement text and removes the old paths.
        """
        placeholder_name = placeholder_info.get('placeholder_name', '')

        # Extract aria-label from element (needed for SKU "RESEARCH USE ONLY" preservation)
        aria_label = element.get('aria-label', '')

        # Get SVG namespace
        ns = '{http://www.w3.org/2000/svg}'

        # Get parent to insert new text element
        parent_map = {c: p for p in element.getroottree().iter() for c in p}
        parent = parent_map.get(element)

        if parent is None:
            logger.error(f"{placeholder_name}: cannot find parent for aria-label element")
            return

        # Extract position from transform attribute
        transform = element.get('transform', '')
        x_pos, y_pos = 0, 0

        # Parse matrix transform: matrix(a,b,c,d,e,f) where e=translateX, f=translateY
        matrix_match = re.search(r'matrix\s*\(\s*([^,]+),\s*([^,]+),\s*([^,]+),\s*([^,]+),\s*([^,]+),\s*([^,\)]+)\)', transform)
        if matrix_match:
            x_pos = float(matrix_match.group(5))
            y_pos = float(matrix_match.group(6))
            logger.info(f"{placeholder_name}: extracted position from matrix: ({x_pos}, {y_pos})")
        else:
            translate_match = re.search(r'translate\s*\(\s*([^,\)]+)(?:,\s*([^,\)]+))?\)', transform)
            if translate_match:
                x_pos = float(translate_match.group(1))
                y_pos = float(translate_match.group(2)) if translate_match.group(2) else 0
                logger.info(f"{placeholder_name}: extracted position from translate: ({x_pos}, {y_pos})")

        # Extract style information
        style = element.get('style', '')
        font_family = self._extract_style_value(style, 'font-family', 'Arial')
        font_size = self._extract_style_value(style, 'font-size', '12px')
        fill = self._extract_style_value(style, 'fill', '#000000')
        font_weight = self._extract_style_value(style, 'font-weight', 'normal')

        # Check if user-defined area exists for this placeholder
        user_area = self.text_areas.get(placeholder_name)

        # Create new text element
        new_text_elem = etree.Element(ns + 'text')

        if user_area:
            area_x = float(user_area['x'])
            area_y = float(user_area['y'])
            area_width = float(user_area['width'])
            area_height = float(user_area['height'])

            # Use TextFormatter to find optimal layout
            formatted = self.formatter.format_text(
                text=new_text,
                placeholder_info=placeholder_info,
                max_width=area_width,
                max_height=area_height,
                placeholder_name=placeholder_name,
            )
            lines = formatted['lines']
            optimal_font_size = float(formatted['font_size'])
            line_height = formatted.get('line_height', optimal_font_size * 1.2)

            # Get text alignment
            text_anchor = self._get_text_anchor(placeholder_name)

            # Calculate X position based on alignment
            if text_anchor == 'start':  # left
                x_pos = area_x
            elif text_anchor == 'end':  # right
                x_pos = area_x + area_width
            else:  # middle (center)
                x_pos = area_x + (area_width / 2)

            total_height = line_height * len(lines)

            new_text_elem.set('text-anchor', text_anchor)
            new_text_elem.set('style', f'font-family:{font_family};font-size:{optimal_font_size:.2f}px;fill:{fill};font-weight:{font_weight}')

            if len(lines) > 1:
                padding = max(0, (area_height - total_height) / 2)
                start_y = area_y + padding + (optimal_font_size * 0.85)
                new_text_elem.set('y', str(start_y))
                new_text_elem.set('x', str(x_pos))
                for i, line_text in enumerate(lines):
                    tspan = etree.SubElement(new_text_elem, ns + 'tspan')
                    tspan.set('x', str(x_pos))
                    tspan.set('text-anchor', text_anchor)
                    tspan.set('dy', '0' if i == 0 else f'{line_height:.1f}')
                    tspan.text = line_text
            else:
                y_pos_area = area_y + (area_height / 2) + (optimal_font_size * 0.35)
                new_text_elem.set('x', str(x_pos))
                new_text_elem.set('y', str(y_pos_area))
                new_text_elem.text = lines[0] if lines else new_text

            new_text_elem.set('aria-label', new_text)
            logger.info(f"{placeholder_name}: created text in user area at ({center_x:.1f}, {area_y:.1f}), font={optimal_font_size:.1f}px, lines={len(lines)}")
        else:
            # No user area (e.g. SKU, RESEARCH USE ONLY) – PRESERVE EXACT POSITION
            # Create text element at the EXACT same position as original paths
            orig = placeholder_info.get('original_full_text', '') or aria_label
            if placeholder_name == 'sku':
                display_text = self._surgical_sku_display_text(orig, new_text)
            else:
                display_text = new_text

            # DON'T use dominant-baseline (not supported on Railway)
            # Instead: use ABSOLUTE positioning with manual baseline offset
            if transform:
                # Parse transform matrix to get actual position
                # matrix(a,b,c,d,e,f) where e=translateX, f=translateY
                import re
                matrix_match = re.search(r'matrix\s*\(\s*([^,]+),\s*([^,]+),\s*([^,]+),\s*([^,]+),\s*([^,]+),\s*([^,\)]+)\)', transform)
                if matrix_match:
                    translate_x = float(matrix_match.group(5))
                    translate_y = float(matrix_match.group(6))

                    # Extract font size to calculate baseline offset
                    font_size_value = float(font_size.replace('px','').replace('pt','')) if isinstance(font_size, str) else float(font_size)

                    # Text baseline is ~85% down from top of em-square
                    # Paths are positioned from top-left, so we add baseline offset
                    baseline_offset = font_size_value * 0.85

                    new_text_elem.set('x', str(translate_x))
                    new_text_elem.set('y', str(translate_y + baseline_offset))
                    logger.info(f"{placeholder_name}: absolute position ({translate_x:.1f}, {translate_y + baseline_offset:.1f}), baseline_offset={baseline_offset:.1f}px")
                else:
                    # Fallback: use x,y from placeholder_info
                    new_text_elem.set('x', str(x_pos))
                    new_text_elem.set('y', str(y_pos))
                    logger.info(f"{placeholder_name}: fallback position ({x_pos}, {y_pos})")
            else:
                new_text_elem.set('x', str(x_pos))
                new_text_elem.set('y', str(y_pos))
                logger.info(f"{placeholder_name}: no transform, position ({x_pos}, {y_pos})")

            new_text_elem.set('style', f'font-family:{font_family};font-size:{font_size};fill:{fill};font-weight:{font_weight}')
            new_text_elem.text = display_text
            new_text_elem.set('aria-label', display_text)

        # Get index of old element
        old_index = list(parent).index(element)

        # Remove old element (path or g with paths)
        parent.remove(element)

        # Insert new text element at same position
        parent.insert(old_index, new_text_elem)

        logger.info(f"{placeholder_name}: replaced aria-label element with new text: {new_text}")
    
    def _extract_style_value(self, style_string: str, property_name: str, default: str) -> str:
        """Extract a CSS property value from style string."""
        if not style_string:
            return default
        
        pattern = rf"{property_name}:\s*([^;]+)"
        match = re.search(pattern, style_string)
        return match.group(1).strip().strip("'\"") if match else default
