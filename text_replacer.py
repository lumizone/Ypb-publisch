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
        'ingredients': ['Ingredients', 'ingredients', 'Composition', 'composition'],
    }

    def __init__(self, template_parser: TemplateParser, text_areas: Dict = None):
        self.parser = template_parser
        self.template_path = template_parser.template_path
        self.formatter = TextFormatter()
        self.text_areas = text_areas or {}  # User-defined text areas: {placeholder_name: {x, y, width, height}}

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

            # Replace each placeholder
            for placeholder_name, placeholder_info in placeholders.items():
                # Support both uppercase (CSV) and lowercase (DataMapper) field names
                value = self._get_product_value(product_data, placeholder_name)
                if not value:
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

        # Display value: surgical SKU replace (only YPB.xxx) vs full replace for name/ingredients
        if placeholder_name == 'sku':
            orig = placeholder_info.get('original_full_text', '')
            display_value = self._surgical_sku_display_text(orig, new_text)
        else:
            display_value = new_text

        # For elements WITHOUT user_area - replace text, preserve position/style
        if not user_area:
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
            text=new_text,
            placeholder_info=placeholder_info,
            max_width=area_width,
            max_height=area_height,
            placeholder_name=placeholder_name,
        )
        lines = formatted['lines']
        optimal_font_size = float(formatted['font_size'])
        line_height = formatted.get('line_height', optimal_font_size * 1.2)

        needs_wrap = len(lines) > 1

        logger.info(f"Formatted '{placeholder_name}': {len(lines)} lines, font={optimal_font_size:.1f}px, "
                    f"area={area_width:.0f}x{area_height:.0f}")

        # Clear existing text nodes
        for child in list(element):
            element.remove(child)
        element.text = None

        # Get SVG namespace
        ns = '{http://www.w3.org/2000/svg}'
        if element.tag.startswith('{'):
            ns = element.tag.rsplit('}', 1)[0] + '}'

        logger.info(f"Using user-defined area for {placeholder_name}: x={area_x:.1f}, y={area_y:.1f}, w={area_width:.1f}, h={area_height:.1f}")

        # Calculate position - center in user area
        center_x = area_x + (area_width / 2)
        total_height = line_height * len(lines)

        if needs_wrap and len(lines) > 1:
            # Multi-line: center horizontally and vertically
            padding = max(0, (area_height - total_height) / 2)
            y_pos = str(area_y + padding + (optimal_font_size * 0.85))
        else:
            # Single line: center both horizontally and vertically
            center_y = area_y + (area_height / 2)
            y_pos = str(center_y + (optimal_font_size * 0.35))

        x_pos = str(center_x)

        # Update element position and style
        element.set('x', x_pos)
        element.set('y', y_pos)
        element.set('text-anchor', 'middle')

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
            tspan_x = str(center_x)
            for i, line_text in enumerate(lines):
                tspan = etree.SubElement(element, ns + 'tspan')
                tspan.set('x', tspan_x)
                tspan.set('text-anchor', 'middle')
                tspan.set('dy', '0' if i == 0 else f'{line_height:.1f}')
                tspan.text = line_text
            logger.info(f"Created {len(lines)} tspans for multi-line text")
        else:
            # Single line text
            element.text = lines[0] if lines else new_text
    
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

            center_x = area_x + (area_width / 2)
            total_height = line_height * len(lines)

            new_text_elem.set('text-anchor', 'middle')
            new_text_elem.set('style', f'font-family:{font_family};font-size:{optimal_font_size:.2f}px;fill:{fill};font-weight:{font_weight}')

            if len(lines) > 1:
                padding = max(0, (area_height - total_height) / 2)
                start_y = area_y + padding + (optimal_font_size * 0.85)
                new_text_elem.set('y', str(start_y))
                new_text_elem.set('x', str(center_x))
                for i, line_text in enumerate(lines):
                    tspan = etree.SubElement(new_text_elem, ns + 'tspan')
                    tspan.set('x', str(center_x))
                    tspan.set('text-anchor', 'middle')
                    tspan.set('dy', '0' if i == 0 else f'{line_height:.1f}')
                    tspan.text = line_text
            else:
                y_pos_area = area_y + (area_height / 2) + (optimal_font_size * 0.35)
                new_text_elem.set('x', str(center_x))
                new_text_elem.set('y', str(y_pos_area))
                new_text_elem.text = lines[0] if lines else new_text

            new_text_elem.set('aria-label', new_text)
            logger.info(f"{placeholder_name}: created text in user area at ({center_x:.1f}, {area_y:.1f}), font={optimal_font_size:.1f}px, lines={len(lines)}")
        else:
            # No user area (e.g. SKU) – use original position; surgical SKU replace
            orig = placeholder_info.get('original_full_text', '') or aria_label
            if placeholder_name == 'sku':
                display_text = self._surgical_sku_display_text(orig, new_text)
            else:
                display_text = new_text

            new_text_elem.set('x', str(x_pos))
            new_text_elem.set('y', str(y_pos))
            new_text_elem.set('style', f'font-family:{font_family};font-size:{font_size};fill:{fill};font-weight:{font_weight}')
            new_text_elem.text = display_text
            new_text_elem.set('aria-label', display_text)
            logger.info(f"{placeholder_name}: created text at original position ({x_pos}, {y_pos})")

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
