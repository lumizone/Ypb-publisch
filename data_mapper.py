"""Data mapper for loading and processing product data from CSV/Google Sheets."""

import csv
from pathlib import Path
from typing import List, Dict, Optional, Tuple
import config


class DataMapperError(Exception):
    """Raised when data mapping fails."""
    pass


class DataMapper:
    """Maps product data from CSV or Google Sheets to template fields."""
    
    def __init__(self, data_source: Path):
        self.data_source = Path(data_source)
        self.products: List[Dict[str, str]] = []
    
    def load_csv(self) -> List[Dict[str, str]]:
        """Load product data from CSV file."""
        if not self.data_source.exists():
            raise DataMapperError(f"CSV file not found: {self.data_source}")
        
        products = []
        
        try:
            with open(self.data_source, 'r', encoding='utf-8-sig') as f:
                # Detect delimiter
                sample = f.read(1024)
                f.seek(0)
                sniffer = csv.Sniffer()
                delimiter = sniffer.sniff(sample).delimiter
                
                reader = csv.DictReader(f, delimiter=delimiter)
                
                # Normalize column names (handle case variations)
                field_mapping = {}
                for col in reader.fieldnames:
                    col_lower = col.lower().strip()
                    if 'product' in col_lower or 'name' in col_lower:
                        field_mapping[col] = 'product_name'
                    elif 'ingredient' in col_lower or 'composition' in col_lower:
                        field_mapping[col] = 'ingredients'
                    elif 'sku' in col_lower:
                        field_mapping[col] = 'sku'
                
                for row_num, row in enumerate(reader, start=2):  # Start at 2 (header is row 1)
                    if not any(row.values()):  # Skip empty rows
                        continue
                    
                    product = {}
                    
                    # Map fields
                    for original_col, normalized_col in field_mapping.items():
                        value = row.get(original_col, '').strip()
                        product[normalized_col] = value
                    
                    # Validate required fields
                    missing = []
                    for field in config.REQUIRED_PLACEHOLDERS:
                        if not product.get(field):
                            missing.append(field)
                    
                    if missing:
                        raise DataMapperError(
                            f"Row {row_num}: Missing required fields: {', '.join(missing)}"
                        )
                    
                    products.append(product)
            
            if not products:
                raise DataMapperError("CSV file contains no valid product rows")
            
            self.products = products
            return products
            
        except csv.Error as e:
            raise DataMapperError(f"CSV parsing error: {e}")
        except Exception as e:
            raise DataMapperError(f"Error loading CSV: {e}")
    
    def get_products(self) -> List[Dict[str, str]]:
        """Get loaded products."""
        if not self.products:
            raise DataMapperError("No products loaded. Call load_csv() first.")
        return self.products
    
    def get_product_count(self) -> int:
        """Get number of products."""
        return len(self.products)
    
    def validate(self) -> Tuple[bool, List[str]]:
        """Validate product data."""
        try:
            if not self.products:
                self.load_csv()
            
            errors = []
            for idx, product in enumerate(self.products, start=1):
                for field in config.REQUIRED_PLACEHOLDERS:
                    if not product.get(field):
                        errors.append(f"Product {idx}: Missing {field}")
            
            return len(errors) == 0, errors
            
        except Exception as e:
            return False, [str(e)]
