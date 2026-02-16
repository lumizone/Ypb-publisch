"""Batch processor for generating multiple labels from a template."""

from pathlib import Path
from typing import List, Dict, Tuple, Optional
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
import time

from template_parser import TemplateParser, TemplateParseError
from data_mapper import DataMapper, DataMapperError
from text_replacer import TextReplacer, TextReplacerError
from renderer import Renderer, RenderError
import config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class BatchProcessorError(Exception):
    """Raised when batch processing fails."""
    pass


class BatchProcessor:
    """Processes batches of products to generate labels."""
    
    def __init__(self, template_path: Path, data_source: Path, text_areas: Dict = None, text_alignments: Dict = None):
        self.template_path = Path(template_path)
        self.data_source = Path(data_source)
        self.text_areas = text_areas
        self.text_alignments = text_alignments or {}
        self.parser: Optional[TemplateParser] = None
        self.mapper: Optional[DataMapper] = None
        self.replacer: Optional[TextReplacer] = None
        self.renderer: Optional[Renderer] = None
        self.errors: List[Dict] = []
        self.success_count = 0
        
    def initialize(self):
        """Initialize all components."""
        try:
            # Parse template
            logger.info(f"Parsing template: {self.template_path}")
            self.parser = TemplateParser(self.template_path)
            placeholders = self.parser.parse()
            logger.info(f"Found placeholders: {list(placeholders.keys())}")
            
            # Load data
            logger.info(f"Loading data from: {self.data_source}")
            self.mapper = DataMapper(self.data_source)
            products = self.mapper.load_csv()
            logger.info(f"Loaded {len(products)} products")
            
            # Initialize replacer with text areas and alignments
            self.replacer = TextReplacer(self.parser, text_areas=self.text_areas, text_alignments=self.text_alignments)
            
            # Initialize renderer
            self.renderer = Renderer()
            
        except (TemplateParseError, DataMapperError) as e:
            raise BatchProcessorError(f"Initialization failed: {e}")
        except Exception as e:
            raise BatchProcessorError(f"Unexpected initialization error: {e}")
    
    def process_product(self, product: Dict[str, str], output_dir: Path) -> Dict:
        """Process a single product and generate its label files."""
        # Support both uppercase (from CSV) and lowercase (from DataMapper) field names
        sku = product.get('SKU') or product.get('sku', 'unknown')
        product_name = product.get('Product') or product.get('product_name', 'unknown')
        
        try:
            # Sanitize filenames
            safe_sku = self._sanitize_filename(sku)
            base_filename = safe_sku
            
            # Replace text in template
            svg_path = self.replacer.replace(product)
            
            # Render to SVG, JPG, and PDF
            base_output_path = output_dir / base_filename
            files = self.renderer.render_all_formats(svg_path, base_output_path)
            
            # Clean up temporary SVG (original temp file, not the saved one)
            temp_svg = config.TEMP_DIR / f"label_{sku}.svg"
            if temp_svg.exists() and temp_svg != files['svg']:
                temp_svg.unlink()
            
            return {
                'status': 'success',
                'sku': sku,
                'product_name': product_name,
                'svg': files['svg'],
                'jpg': files['jpg']
            }
            
        except (TextReplacerError, RenderError) as e:
            error_msg = f"SKU {sku}: {str(e)}"
            logger.error(error_msg)
            return {
                'status': 'error',
                'sku': sku,
                'product_name': product_name,
                'error': error_msg
            }
        except Exception as e:
            error_msg = f"SKU {sku}: Unexpected error - {str(e)}"
            logger.error(error_msg)
            return {
                'status': 'error',
                'sku': sku,
                'product_name': product_name,
                'error': error_msg
            }
    
    def process_batch(self, output_dir: Path = None, max_workers: int = 1, limit: int = None) -> Dict:
        """Process all products in batch."""
        if output_dir is None:
            output_dir = config.OUTPUT_DIR
        
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Initialize if not already done
        if not self.parser:
            self.initialize()
        
        products = self.mapper.get_products()
        # Limit number of products if specified
        if limit is not None and limit > 0:
            products = products[:limit]
            logger.info(f"Limited batch processing to {limit} products")
        total = len(products)
        
        logger.info(f"Starting batch processing: {total} products")
        start_time = time.time()
        
        results = []
        self.errors = []
        self.success_count = 0
        
        # Process sequentially or in parallel
        if max_workers == 1:
            # Sequential processing
            for idx, product in enumerate(products, 1):
                logger.info(f"Processing {idx}/{total}: {product.get('Product') or product.get('product_name')} ({product.get('SKU') or product.get('sku')})")
                result = self.process_product(product, output_dir)
                results.append(result)
                
                if result['status'] == 'success':
                    self.success_count += 1
                else:
                    self.errors.append(result)
        else:
            # Parallel processing
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_product = {
                    executor.submit(self.process_product, product, output_dir): product
                    for product in products
                }
                
                for idx, future in enumerate(as_completed(future_to_product), 1):
                    product = future_to_product[future]
                    logger.info(f"Completed {idx}/{total}: {product.get('Product') or product.get('product_name')} ({product.get('SKU') or product.get('sku')})")
                    
                    try:
                        result = future.result()
                        results.append(result)
                        
                        if result['status'] == 'success':
                            self.success_count += 1
                        else:
                            self.errors.append(result)
                    except Exception as e:
                        error_result = {
                            'status': 'error',
                            'sku': product.get('SKU') or product.get('sku', 'unknown'),
                            'product_name': product.get('Product') or product.get('product_name', 'unknown'),
                            'error': str(e)
                        }
                        results.append(error_result)
                        self.errors.append(error_result)
        
        elapsed_time = time.time() - start_time
        
        summary = {
            'total': total,
            'success': self.success_count,
            'errors': len(self.errors),
            'elapsed_time': elapsed_time,
            'results': results,
            'output_dir': output_dir
        }
        
        logger.info(f"Batch processing complete: {self.success_count}/{total} succeeded in {elapsed_time:.2f}s")
        
        if self.errors:
            logger.warning(f"Errors encountered: {len(self.errors)}")
            for error in self.errors[:10]:  # Log first 10 errors
                logger.warning(f"  - {error.get('error', 'Unknown error')}")
        
        return summary
    
    def _sanitize_filename(self, filename: str) -> str:
        """Sanitize filename to remove invalid characters."""
        # Remove or replace invalid characters
        invalid_chars = '<>:"/\\|?*'
        for char in invalid_chars:
            filename = filename.replace(char, '_')
        
        # Limit length
        if len(filename) > 100:
            filename = filename[:100]
        
        return filename.strip()
