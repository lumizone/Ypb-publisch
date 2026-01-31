"""Renderer for exporting labels as PNG (300 DPI) and PDF (vector)."""

from pathlib import Path
from typing import Tuple, Optional, Dict
import logging
import subprocess
import shutil

logger = logging.getLogger(__name__)

# Check for cairosvg availability
try:
    import cairosvg
    CAIROSVG_AVAILABLE = True
except (ImportError, OSError):
    CAIROSVG_AVAILABLE = False
    logger.info("cairosvg not available - will use Inkscape for PNG rendering")

# Check for Inkscape (fallback for PNG rendering)
INKSCAPE_PATH = shutil.which('inkscape') or '/opt/homebrew/bin/inkscape'
INKSCAPE_AVAILABLE = Path(INKSCAPE_PATH).exists() if INKSCAPE_PATH else False
if INKSCAPE_AVAILABLE:
    logger.info(f"Inkscape available at: {INKSCAPE_PATH}")

# Core libraries for PDF
try:
    from svglib.svglib import svg2rlg
    from reportlab.graphics import renderPDF
    from PIL import Image
    SVGLIB_AVAILABLE = True
except ImportError:
    SVGLIB_AVAILABLE = False
    logger.warning("svglib/reportlab not available")

import config


class RenderError(Exception):
    """Raised when rendering fails."""
    pass


class Renderer:
    """Renders SVG labels to PNG and PDF formats."""

    def __init__(self):
        if not SVGLIB_AVAILABLE:
            raise RenderError(
                "Required rendering libraries not installed. "
                "Run: pip install svglib reportlab Pillow"
            )
        if not CAIROSVG_AVAILABLE and not INKSCAPE_AVAILABLE:
            logger.warning("Neither cairosvg nor Inkscape available - PNG rendering may fail")
    
    def render_png(self, svg_path: Path, output_path: Path, dpi: int = None) -> Path:
        """Render SVG to PNG at specified DPI."""
        if dpi is None:
            dpi = config.PNG_DPI

        # Try cairosvg first (best quality)
        if CAIROSVG_AVAILABLE:
            try:
                cairosvg.svg2png(
                    url=str(svg_path),
                    write_to=str(output_path),
                    output_width=None,
                    output_height=None,
                    dpi=dpi
                )

                if output_path.exists():
                    return output_path
            except Exception as e:
                logger.warning(f"cairosvg failed: {e}, trying Inkscape")

        # Fallback: Use Inkscape CLI
        if INKSCAPE_AVAILABLE:
            try:
                # Inkscape 1.x command line syntax
                result = subprocess.run([
                    INKSCAPE_PATH,
                    str(svg_path),
                    '--export-type=png',
                    f'--export-filename={output_path}',
                    f'--export-dpi={dpi}'
                ], capture_output=True, text=True, timeout=60)

                if result.returncode == 0 and output_path.exists():
                    logger.info(f"Rendered PNG using Inkscape: {output_path}")
                    return output_path
                else:
                    logger.warning(f"Inkscape failed: {result.stderr}")
            except subprocess.TimeoutExpired:
                logger.warning("Inkscape timed out")
            except Exception as e:
                logger.warning(f"Inkscape error: {e}")

        raise RenderError(f"PNG rendering failed - neither cairosvg nor Inkscape available")
    
    def render_pdf(self, svg_path: Path, output_path: Path) -> Path:
        """Render SVG to vector PDF."""
        try:
            # Use svglib to convert SVG to ReportLab drawing
            drawing = svg2rlg(str(svg_path))
            
            if drawing is None:
                raise RenderError(f"Failed to parse SVG: {svg_path}")
            
            # Render to PDF (vector preserved)
            renderPDF.drawToFile(drawing, str(output_path))
            
            if not output_path.exists():
                raise RenderError(f"PDF file was not created: {output_path}")
            
            return output_path
            
        except Exception as e:
            raise RenderError(f"PDF rendering failed: {e}")
    
    def render_both(self, svg_path: Path, base_output_path: Path) -> Tuple[Path, Path]:
        """Render both PNG and PDF versions."""
        png_path = base_output_path.with_suffix('.png')
        pdf_path = base_output_path.with_suffix('.pdf')
        
        self.render_png(svg_path, png_path)
        self.render_pdf(svg_path, pdf_path)
        
        return png_path, pdf_path
    
    def render_jpg(self, svg_path: Path, output_path: Path, dpi: int = None) -> Path:
        """Render SVG to JPG at specified DPI."""
        if dpi is None:
            dpi = config.PNG_DPI
        
        try:
            # First render to PNG, then convert to JPG
            import tempfile
            temp_png = output_path.with_suffix('.tmp.png')
            
            # Render PNG
            self.render_png(svg_path, temp_png, dpi)
            
            # Convert PNG to JPG using PIL
            img = Image.open(temp_png)
            # Convert RGBA to RGB if needed
            if img.mode in ('RGBA', 'LA', 'P'):
                rgb_img = Image.new('RGB', img.size, (255, 255, 255))
                if img.mode == 'P':
                    img = img.convert('RGBA')
                rgb_img.paste(img, mask=img.split()[-1] if img.mode in ('RGBA', 'LA') else None)
                img = rgb_img
            elif img.mode != 'RGB':
                img = img.convert('RGB')
            
            # Save as JPG with high quality
            img.save(output_path, 'JPEG', quality=95, dpi=(dpi, dpi))
            
            # Clean up temp PNG
            if temp_png.exists():
                temp_png.unlink()
            
            if not output_path.exists():
                raise RenderError(f"JPG file was not created: {output_path}")
            
            return output_path
            
        except Exception as e:
            raise RenderError(f"JPG rendering failed: {e}")
    
    def render_all_formats(self, svg_path: Path, base_output_path: Path) -> Dict[str, Path]:
        """Render SVG, JPG, and PDF versions. Returns dict with 'svg', 'jpg', 'pdf'."""
        jpg_path = base_output_path.with_suffix('.jpg')
        pdf_path = base_output_path.with_suffix('.pdf')
        
        # Keep SVG (copy it)
        svg_output_path = base_output_path.with_suffix('.svg')
        if svg_path != svg_output_path:
            import shutil
            shutil.copy2(svg_path, svg_output_path)
        
        # Render JPG and PDF
        self.render_jpg(svg_path, jpg_path)
        self.render_pdf(svg_path, pdf_path)
        
        return {
            'svg': svg_output_path,
            'jpg': jpg_path,
            'pdf': pdf_path
        }
    
    def validate_svg(self, svg_path: Path) -> bool:
        """Validate SVG file is renderable."""
        try:
            # Try to parse SVG
            from lxml import etree
            tree = etree.parse(str(svg_path))
            return True
        except Exception:
            return False
