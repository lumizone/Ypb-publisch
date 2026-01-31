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

            for placeholder in config.REQUIRED_PLACEHOLDERS:
                candidates = root.findall(f".//*[@data-placeholder='{placeholder}']", namespaces)
                if not candidates:
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

                style = style_element.get('style', '')
                x = style_element.get('x', '0')
                y = style_element.get('y', '0')
                font_family = self._extract_style(style, 'font-family', 'Arial')
                # Check for font-size as direct attribute first, then in style string
                font_size = style_element.get('font-size') or self._extract_style(style, 'font-size', '12')
                fill = self._extract_style(style, 'fill', '#000000')
                text_anchor = style_element.get('text-anchor', 'start')
                transform = element.get('transform', '')

                placeholders[placeholder] = {
                    'element': element,
                    'x': x,
                    'y': y,
                    'font-family': font_family,
                    'font-size': font_size,
                    'fill': fill,
                    'text-anchor': text_anchor,
                    'style': style,
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
