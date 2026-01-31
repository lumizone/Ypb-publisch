"""Packaging module for organizing and compressing output files."""

from pathlib import Path
from typing import List, Dict, Optional
import zipfile
import logging
import config

logger = logging.getLogger(__name__)


class PackagerError(Exception):
    """Raised when packaging fails."""
    pass


class Packager:
    """Packages generated labels into organized ZIP archives."""
    
    def __init__(self):
        pass
    
    def create_zip(self, output_dir: Path, zip_path: Path = None, 
                   subfolder: str = "labels") -> Path:
        """Create ZIP archive of all label files."""
        if zip_path is None:
            zip_path = config.OUTPUT_DIR / "labels_batch.zip"
        
        zip_path = Path(zip_path)
        output_dir = Path(output_dir)
        
        if not output_dir.exists():
            raise PackagerError(f"Output directory does not exist: {output_dir}")
        
        logger.info(f"Creating ZIP archive: {zip_path}")
        
        try:
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                # Add all PNG and PDF files
                files_added = 0
                for file_path in sorted(output_dir.glob("*")):
                    if file_path.is_file() and file_path.suffix.lower() in ['.png', '.pdf']:
                        # Add to ZIP with subfolder structure
                        archive_path = f"{subfolder}/{file_path.name}"
                        zipf.write(file_path, archive_path)
                        files_added += 1
                
                if files_added == 0:
                    raise PackagerError(f"No label files found in {output_dir}")
                
                logger.info(f"Added {files_added} files to ZIP archive")
            
            return zip_path
            
        except Exception as e:
            raise PackagerError(f"Failed to create ZIP archive: {e}")
    
    def create_zip_from_results(self, results: List[Dict], zip_path: Path = None,
                                subfolder: str = "labels", limit: int = None) -> Path:
        """Create ZIP archive from batch processing results.
        Structure: SKU/SVG/file.svg, SKU/JPG/file.jpg, SKU/PDF/file.pdf
        """
        if zip_path is None:
            zip_path = config.OUTPUT_DIR / "labels_batch.zip"
        
        zip_path = Path(zip_path)
        
        # Limit to first N successful results
        successful_results = [r for r in results if r.get('status') == 'success']
        if limit is not None and limit > 0:
            successful_results = successful_results[:limit]
        
        logger.info(f"Creating ZIP archive from {len(successful_results)} results: {zip_path}")
        
        try:
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                files_added = 0
                
                for result in successful_results:
                    sku = result.get('sku', 'unknown')
                    # Sanitize SKU for folder name
                    safe_sku = self._sanitize_filename(sku)
                    
                    # Get base filename (without path and extension)
                    base_name = None
                    
                    # Add SVG
                    svg_path = result.get('svg')
                    if svg_path and Path(svg_path).exists():
                        svg_file = Path(svg_path)
                        base_name = svg_file.stem
                        archive_path = f"{safe_sku}/SVG/{svg_file.name}"
                        zipf.write(svg_path, archive_path)
                        files_added += 1
                    
                    # Add JPG
                    jpg_path = result.get('jpg')
                    if jpg_path and Path(jpg_path).exists():
                        jpg_file = Path(jpg_path)
                        if base_name is None:
                            base_name = jpg_file.stem
                        archive_path = f"{safe_sku}/JPG/{jpg_file.name}"
                        zipf.write(jpg_path, archive_path)
                        files_added += 1
                    
                    # Add PDF
                    pdf_path = result.get('pdf')
                    if pdf_path and Path(pdf_path).exists():
                        pdf_file = Path(pdf_path)
                        if base_name is None:
                            base_name = pdf_file.stem
                        archive_path = f"{safe_sku}/PDF/{pdf_file.name}"
                        zipf.write(pdf_path, archive_path)
                        files_added += 1
                
                if files_added == 0:
                    raise PackagerError("No successful label files to package")
                
                logger.info(f"Added {files_added} files to ZIP archive")
            
            return zip_path
            
        except Exception as e:
            raise PackagerError(f"Failed to create ZIP archive: {e}")
    
    def _sanitize_filename(self, filename: str) -> str:
        """Sanitize filename to remove invalid characters."""
        invalid_chars = '<>:"/\\|?*'
        for char in invalid_chars:
            filename = filename.replace(char, '_')
        if len(filename) > 100:
            filename = filename[:100]
        return filename.strip()