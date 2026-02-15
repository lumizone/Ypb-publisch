"""CSV manager for reading, writing, and updating product database."""

import csv
from pathlib import Path
from typing import List, Dict, Optional
import config


class CSVManagerError(Exception):
    """Raised when CSV operations fail."""
    pass


class CSVManager:
    """Manages CSV database operations."""
    
    def __init__(self, csv_path: Path):
        self.csv_path = Path(csv_path)
        self.original_columns = ['Product', 'Ingredients', 'SKU']
    
    def read_all(self) -> List[Dict[str, str]]:
        """Read all products from CSV."""
        if not self.csv_path.exists():
            raise CSVManagerError(f"CSV file not found: {self.csv_path}")
        
        products = []
        
        try:
            with open(self.csv_path, 'r', encoding='utf-8-sig') as f:
                sample = f.read(1024)
                f.seek(0)
                sniffer = csv.Sniffer()
                delimiter = sniffer.sniff(sample).delimiter
                
                reader = csv.DictReader(f, delimiter=delimiter)
                
                # Get actual column names from file
                if reader.fieldnames:
                    self.original_columns = list(reader.fieldnames)
                
                for idx, row in enumerate(reader):
                    # Get values from any column name variation
                    product_name = ''
                    ingredients = ''
                    sku = ''
                    cas = ''
                    mw = ''

                    # Try direct column name first (case-insensitive)
                    for col_name, value in row.items():
                        col_clean = col_name.strip()
                        col_lower = col_clean.lower()

                        # Match Product column - exact match first, then contains
                        if col_lower == 'product' or col_lower.startswith('product'):
                            product_name = (value or '').strip()
                        # Match Ingredients column
                        elif col_lower == 'ingredients' or 'ingredient' in col_lower or 'composition' in col_lower or 'dosage' in col_lower:
                            ingredients = (value or '').strip()
                        # Match SKU column
                        elif col_lower == 'sku' or col_lower.startswith('sku'):
                            sku = (value or '').strip()
                        # Match CAS column
                        elif col_lower in ('cas', 'cas number', 'cas_number') or 'cas' in col_lower:
                            cas = (value or '').strip()
                        # Match MW column
                        elif col_lower in ('m.w.', 'mw', 'molecular weight', 'molecular_weight') or 'molecular' in col_lower:
                            mw = (value or '').strip()
                    
                    # Add product if at least one field has data
                    if product_name or ingredients or sku:
                        product = {
                            'id': len(products) + 1,
                            'Product': product_name,
                            'Ingredients': ingredients,
                            'SKU': sku,
                            'CAS': cas,
                            'MW': mw
                        }
                        products.append(product)
            
            return products
            
        except Exception as e:
            raise CSVManagerError(f"Error reading CSV: {e}")
    
    def save_all(self, products: List[Dict[str, str]]) -> None:
        """Save all products to CSV."""
        try:
            # Remove 'id' field if present and filter empty rows
            cleaned_products = []
            for product in products:
                cleaned = {
                    'Product': product.get('Product', '').strip(),
                    'Ingredients': product.get('Ingredients', '').strip(),
                    'SKU': product.get('SKU', '').strip(),
                    'CAS': product.get('CAS', '').strip(),
                    'MW': product.get('MW', '').strip()
                }
                # Only add if at least one field is filled
                if cleaned['Product'] or cleaned['Ingredients'] or cleaned['SKU']:
                    cleaned_products.append(cleaned)

            # Ensure directory exists
            self.csv_path.parent.mkdir(parents=True, exist_ok=True)

            with open(self.csv_path, 'w', encoding='utf-8', newline='') as f:
                # Use standard column names
                writer = csv.DictWriter(f, fieldnames=['Product', 'Ingredients', 'SKU', 'CAS', 'MW'], delimiter=',')
                writer.writeheader()
                writer.writerows(cleaned_products)
            
        except Exception as e:
            raise CSVManagerError(f"Error saving CSV: {e}")
    
    def add_product(self, product: Dict[str, str]) -> Dict[str, str]:
        """Add a new product."""
        products = self.read_all()
        
        # Get next ID
        max_id = max([p['id'] for p in products], default=0)
        
        new_product = {
            'id': max_id + 1,
            'Product': product.get('Product', '').strip(),
            'Ingredients': product.get('Ingredients', '').strip(),
            'SKU': product.get('SKU', '').strip(),
            'CAS': product.get('CAS', '').strip(),
            'MW': product.get('MW', '').strip()
        }
        
        products.append(new_product)
        self.save_all(products)
        
        return new_product
    
    def update_product(self, product_id: int, updates: Dict[str, str]) -> Dict[str, str]:
        """Update a product by ID."""
        products = self.read_all()
        
        product = None
        for p in products:
            if p['id'] == product_id:
                product = p
                break
        
        if not product:
            raise CSVManagerError(f"Product ID {product_id} not found")
        
        # Update only provided fields
        if 'Product' in updates:
            product['Product'] = str(updates['Product']).strip()
        if 'Ingredients' in updates:
            product['Ingredients'] = str(updates['Ingredients']).strip()
        if 'SKU' in updates:
            product['SKU'] = str(updates['SKU']).strip()
        if 'CAS' in updates:
            product['CAS'] = str(updates['CAS']).strip()
        if 'MW' in updates:
            product['MW'] = str(updates['MW']).strip()
        
        self.save_all(products)
        return product
    
    def delete_product(self, product_id: int) -> None:
        """Delete a product by ID."""
        products = self.read_all()
        
        # Find and remove product
        product = None
        for i, p in enumerate(products):
            if p['id'] == product_id:
                product = products.pop(i)
                break
        
        if not product:
            raise CSVManagerError(f"Product ID {product_id} not found")
        
        # Reassign IDs sequentially
        for i, p in enumerate(products, start=1):
            p['id'] = i
        
        self.save_all(products)
    
    def bulk_update(self, updates: List[Dict[str, any]]) -> List[Dict[str, str]]:
        """Bulk update multiple products."""
        products = self.read_all()
        
        # Create lookup map
        product_map = {p['id']: p for p in products}
        
        for update in updates:
            product_id = update.get('id')
            if product_id and product_id in product_map:
                product = product_map[product_id]
                # Only update fields that are explicitly provided (not None or empty string unless intended)
                if 'Product' in update:
                    product['Product'] = str(update['Product']).strip()
                if 'Ingredients' in update:
                    product['Ingredients'] = str(update['Ingredients']).strip()
                if 'SKU' in update:
                    product['SKU'] = str(update['SKU']).strip()
                if 'CAS' in update:
                    product['CAS'] = str(update['CAS']).strip()
                if 'MW' in update:
                    product['MW'] = str(update['MW']).strip()
        
        self.save_all(products)
        return self.read_all()
    
    def replace_csv(self, new_csv_path: Path) -> None:
        """Replace the current CSV file with a new one."""
        if not new_csv_path.exists():
            raise CSVManagerError(f"New CSV file not found: {new_csv_path}")
        
        # Validate the new CSV
        try:
            with open(new_csv_path, 'r', encoding='utf-8-sig') as f:
                sample = f.read(1024)
                f.seek(0)
                sniffer = csv.Sniffer()
                delimiter = sniffer.sniff(sample).delimiter
                reader = csv.DictReader(f, delimiter=delimiter)
                
                if not reader.fieldnames:
                    raise CSVManagerError("New CSV file has no headers")
                
                # Check if required columns exist
                fieldnames_lower = [f.lower() for f in reader.fieldnames]
                has_product = any('product' in f or 'name' in f for f in fieldnames_lower)
                has_ingredients = any('ingredient' in f or 'composition' in f or 'dosage' in f for f in fieldnames_lower)
                has_sku = any('sku' in f for f in fieldnames_lower)
                has_cas = any('cas' in f for f in fieldnames_lower)
                has_mw = any('m.w' in f or 'mw' in f or 'molecular' in f for f in fieldnames_lower)

                if not (has_product and has_ingredients and has_sku and has_cas and has_mw):
                    raise CSVManagerError("New CSV must have Product, Ingredients, SKU, CAS, and MW columns")
        
        except Exception as e:
            raise CSVManagerError(f"Invalid CSV file: {e}")
        
        # Backup current file
        backup_path = self.csv_path.with_suffix('.csv.backup')
        if self.csv_path.exists():
            import shutil
            shutil.copy2(self.csv_path, backup_path)
        
        # Copy new file
        import shutil
        shutil.copy2(new_csv_path, self.csv_path)
        
        # Update column names if different
        with open(self.csv_path, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            if reader.fieldnames:
                self.original_columns = list(reader.fieldnames)
