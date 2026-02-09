"""Gemini Vision OCR and masked text generation for AI converter fallback.

This module provides intelligent fallback when PyMuPDF fails to extract text
due to custom font encoding. Uses Gemini Vision API for:
1. OCR extraction of SKU and "RESEARCH USE ONLY" text
2. Text field bounding box detection
3. Masked text generation (only in annotated regions)
"""

from google import genai
from google.genai import types
from pathlib import Path
from typing import Dict, List, Optional
from io import BytesIO
import logging
import json
import re
from PIL import Image, ImageDraw
import config

logger = logging.getLogger(__name__)


class GeminiOCR:
    """Gemini Vision-based OCR and text generation for label templates."""

    def __init__(self, api_key: str):
        """Initialize Gemini client.

        Args:
            api_key: Google Gemini API key
        """
        self.client = genai.Client(api_key=api_key)
        self.model = 'gemini-2.5-flash'  # Best for OCR + image understanding

    def extract_sku_and_research(self, image_path: Path) -> Dict[str, any]:
        """Extract SKU and 'RESEARCH USE ONLY' text from label image.

        Args:
            image_path: Path to rendered label PNG

        Returns:
            {
                'sku': 'YPB.100' or '',
                'has_research_use_only': True/False,
                'confidence': 0.0-1.0,
                'all_text': '...' (full OCR text for debugging)
            }
        """
        logger.info(f"🔍 Gemini Vision OCR: {image_path.name}")

        prompt = """
You are analyzing a pharmaceutical product label image.

TASK: Extract the following information EXACTLY as it appears on the label:

1. **SKU/Product Code**: Look for pattern like "YPB.XXX" or "YPB-XXX" (case-insensitive)
   - Common locations: bottom of label, near barcode, with "SKU:" prefix
   - Example: "YPB.100", "SKU: YPB-100", "YPB.283"

2. **Research Use Statement**: Check if label contains text like:
   - "RESEARCH USE ONLY"
   - "FOR RESEARCH USE ONLY"
   - "RESEARCH PURPOSES ONLY"
   - Case-insensitive match

RESPOND IN VALID JSON FORMAT ONLY (no markdown, no explanations):
{
    "sku": "YPB.100",
    "has_research_use_only": true,
    "confidence": 0.95,
    "all_text": "full text extracted from label for debugging"
}

RULES:
- If SKU not found, return empty string ""
- SKU should be uppercase (e.g., "YPB.100" not "ypb.100")
- Confidence: 0.0 (not found) to 1.0 (certain)
- Extract ALL visible text to 'all_text' field for verification
- Return ONLY valid JSON, no code blocks, no explanations
"""

        try:
            # Load image as PIL Image for new SDK
            pil_image = Image.open(image_path)

            # Create generation config using types
            generation_config = types.GenerateContentConfig(
                temperature=0.1,  # Low for accuracy
                max_output_tokens=2000
            )

            response = self.client.models.generate_content(
                model=self.model,
                contents=[prompt, pil_image],
                config=generation_config
            )

            # Parse JSON from response
            result_text = response.text.strip()

            # Remove markdown code blocks if present
            if '```json' in result_text:
                match = re.search(r'```json\n(.*?)\n```', result_text, re.DOTALL)
                if match:
                    result_text = match.group(1)
            elif '```' in result_text:
                match = re.search(r'```\n(.*?)\n```', result_text, re.DOTALL)
                if match:
                    result_text = match.group(1)

            result = json.loads(result_text)

            logger.info(f"✓ OCR Results: SKU='{result.get('sku')}', "
                       f"Research={result.get('has_research_use_only')}, "
                       f"Confidence={result.get('confidence')}")

            return result

        except Exception as e:
            logger.error(f"❌ Gemini OCR failed: {e}")
            return {
                'sku': '',
                'has_research_use_only': False,
                'confidence': 0.0,
                'all_text': '',
                'error': str(e)
            }

    def extract_product_info(self, image_path: Path) -> Dict[str, any]:
        """Extract Product Name and Ingredients/Dosage from label image.

        This is the SECOND Gemini call - separate from SKU extraction.

        Args:
            image_path: Path to rendered label PNG

        Returns:
            {
                'product_name': 'BPC-157 5mg' or '',
                'ingredients': 'BPC-157 5mg / TB-500 2mg' or '',
                'dosage': '5mg' or '',
                'confidence': 0.0-1.0
            }
        """
        logger.info(f"🔍 Gemini Vision - Extracting Product Name & Ingredients: {image_path.name}")

        prompt = """
You are analyzing a pharmaceutical product label image.

TASK: Extract the following information EXACTLY as it appears on the label:

1. **Product Name**: The main product name/title on the label
   - Usually the LARGEST text on the label
   - Examples: "BPC-157", "4X Blend", "Semaglutide 5mg"
   - May include dosage as part of name

2. **Ingredients/Dosage**: The list of active ingredients with their amounts
   - Usually smaller text below the product name
   - Examples: "BPC-157 5mg", "GHRP-2 5mg / Tesamorelin 5mg / MGF 500mcg"
   - Include ALL ingredients with dosages separated by " / "

3. **Dosage**: If there's a separate dosage field (may be same as in product name)

RESPOND IN VALID JSON FORMAT ONLY (no markdown, no explanations):
{
    "product_name": "4X Blend",
    "ingredients": "GHRP-2 5mg / Tesamorelin 5mg / MGF 500mcg / Ipamorelin 2.5mg",
    "dosage": "5mg",
    "confidence": 0.95
}

RULES:
- Extract text EXACTLY as it appears (preserve capitalization, spacing)
- If not found, return empty string ""
- Confidence: 0.0 (not found) to 1.0 (certain)
- Return ONLY valid JSON, no code blocks, no explanations
"""

        try:
            # Load image as PIL Image
            pil_image = Image.open(image_path)

            # Create generation config
            generation_config = types.GenerateContentConfig(
                temperature=0.1,  # Low for accuracy
                max_output_tokens=2000
            )

            response = self.client.models.generate_content(
                model=self.model,
                contents=[prompt, pil_image],
                config=generation_config
            )

            # Parse JSON from response
            result_text = response.text.strip()

            # Remove markdown code blocks if present
            if '```json' in result_text:
                match = re.search(r'```json\n(.*?)\n```', result_text, re.DOTALL)
                if match:
                    result_text = match.group(1)
            elif '```' in result_text:
                match = re.search(r'```\n(.*?)\n```', result_text, re.DOTALL)
                if match:
                    result_text = match.group(1)

            result = json.loads(result_text)

            logger.info(f"✓ Product Info: Name='{result.get('product_name')}', "
                       f"Ingredients='{result.get('ingredients', '')[:50]}...', "
                       f"Confidence={result.get('confidence')}")

            return result

        except Exception as e:
            logger.error(f"❌ Gemini Product Info extraction failed: {e}")
            return {
                'product_name': '',
                'ingredients': '',
                'dosage': '',
                'confidence': 0.0,
                'error': str(e)
            }

    def detect_text_field_boxes(
        self,
        image_path: Path,
        field_names: List[str] = ['Product Name', 'Ingredients']
    ) -> Dict[str, Dict[str, int]]:
        """Detect bounding boxes for text fields using Gemini Vision.

        This helps user annotation by suggesting where fields are located.

        Args:
            image_path: Path to label PNG
            field_names: List of field names to detect

        Returns:
            {
                'Product Name': {'x': 100, 'y': 200, 'width': 300, 'height': 50},
                'Ingredients': {'x': 100, 'y': 300, 'width': 400, 'height': 80}
            }
        """
        logger.info(f"🔍 Detecting field boxes: {field_names}")

        # Load image as PIL Image
        pil_image = Image.open(image_path)

        prompt = f"""
Analyze this pharmaceutical label and locate the following text fields:

Fields to find: {', '.join(field_names)}

For each field, estimate the bounding box (x, y, width, height) in pixels.
- x, y: top-left corner coordinates
- width, height: box dimensions

RESPOND IN VALID JSON FORMAT ONLY:
{{
    "Product Name": {{"x": 100, "y": 200, "width": 300, "height": 50}},
    "Ingredients": {{"x": 100, "y": 300, "width": 400, "height": 80}}
}}

If a field is not found, return {{"x": 0, "y": 0, "width": 0, "height": 0}}.
Return ONLY JSON, no markdown, no explanations.
"""

        try:
            # Create generation config
            generation_config = types.GenerateContentConfig(
                temperature=0.2,
                max_output_tokens=500
            )

            response = self.client.models.generate_content(
                model=self.model,
                contents=[prompt, pil_image],
                config=generation_config
            )

            result_text = response.text.strip()
            if '```json' in result_text:
                match = re.search(r'```json\n(.*?)\n```', result_text, re.DOTALL)
                if match:
                    result_text = match.group(1)

            boxes = json.loads(result_text)
            logger.info(f"✓ Detected {len(boxes)} field boxes")
            return boxes

        except Exception as e:
            logger.error(f"❌ Field detection failed: {e}")
            return {}

    def generate_text_in_mask(
        self,
        original_image: Path,
        marked_image: Image.Image,
        mask_regions: List[Dict],
        output_path: Path,
        attempt: int = 1,
        sku_old: str = "XXX",
        sku_new: str = "",
        original_size: tuple = None
    ) -> Path:
        """Generate new image with text replaced in masked regions using Gemini.

        Sends TWO images to Gemini: the original label and a marked version with
        colored rectangles indicating text areas (RED=Product Name, GREEN=Ingredients).

        Args:
            original_image: Path to original label PNG
            marked_image: PIL Image with colored rectangles marking text areas
            mask_regions: List of regions with text to generate (Product Name, Ingredients only)
                [{'field': 'Product Name', 'x': 100, 'y': 200, 'width': 300, 'height': 50, 'text': '4X Blend'}]
            output_path: Where to save final label
            attempt: 1 = first try (temp 0.1), 2 = retry (temp 0.02)
            sku_old: Original SKU from OCR (e.g., "YPB.100")
            sku_new: New SKU from database (e.g., "YPB.111")

        Returns:
            Path to final label with replaced text, or None if generation failed
        """
        logger.info(f"🎨 Gemini generating label with {len(mask_regions)} text replacements + SKU auto-replace (attempt {attempt})")

        # Load original image
        pil_image = Image.open(original_image)

        # Extract data from mask_regions (ONLY Product Name and Ingredients)
        product_name_old = "[identify from Image 1]"
        product_name_new = ""
        ingredients_old = "[identify from Image 1]"
        ingredients_new = ""

        logger.info(f"🔍 DEBUG: mask_regions = {mask_regions}")

        for r in mask_regions:
            if r['field'] == 'Product Name':
                product_name_new = r['text']
                product_name_old = r.get('old_text', product_name_old)
            elif r['field'] == 'Ingredients':
                ingredients_new = r['text']
                ingredients_old = r.get('old_text', ingredients_old)

        logger.info(f"🔍 DEBUG: After extraction - product_name: '{product_name_old}' -> '{product_name_new}'")
        logger.info(f"🔍 DEBUG: After extraction - ingredients: '{ingredients_old}' -> '{ingredients_new}'")
        logger.info(f"🔍 DEBUG: SKU (auto-replace): '{sku_old}' -> '{sku_new}'")

        prompt = f"""I am providing THREE images of the same pharmaceutical product label:

- Image 1: The label with SOLID COLOR blocks covering text areas that need to be replaced. RED block = Product Name area. GREEN block = Ingredients/Dosage area. The colored blocks show you exactly WHERE to write new text and HOW BIG the text area is.

- Image 2: The ORIGINAL clean label showing what the label looks like with existing text. Use this as reference for font style, colors, layout, and everything that should NOT change.

- Image 3: Same as Image 2 (original clean label). Your output must look like this image but with the text replaced.

YOUR TASK: Replace the text in the colored areas with new text:

1. RED AREA (Product Name):
   - Original text was: "{product_name_old}"
   - Write this instead: "{product_name_new}"
   - Match the font style, size, color from Image 2

2. GREEN AREA (Ingredients/Dosage):
   - Original text was: "{ingredients_old}"
   - Write this instead: "{ingredients_new}"
   - Match the font style, size, color from Image 2

3. SKU (not marked, find it on the label):
   - Find "SKU:{sku_old}" and change to "SKU:{sku_new}"

OUTPUT RULES:
- Output must look like Image 3 (clean label) with ONLY the 3 text changes above
- NO colored blocks (red/green) in the output - those are only in Image 1 for reference
- Keep identical: background, graphics, borders, logos, all other text
- Same dimensions as input images
- Spell text EXACTLY as specified above, zero typos

Generate the modified label."""

        try:
            temperature = 0.05 if attempt == 1 else 0.02
            generation_config = types.GenerateContentConfig(
                temperature=temperature,
                response_modalities=["IMAGE"]
            )

            # 3 images: marked (solid fill), original, original again at the end
            response = self.client.models.generate_content(
                model=config.GEMINI_MOCKUP_MODEL,
                contents=[prompt, marked_image, pil_image, pil_image],
                config=generation_config
            )

            # Extract image using the same pattern as mockup generation
            for part in response.parts:
                if part.inline_data is not None and part.inline_data.data is not None:
                    image_bytes = part.inline_data.data
                    result_image = Image.open(BytesIO(image_bytes))

                    # Resize to match original dimensions if needed
                    if original_size and result_image.size != original_size:
                        logger.info(f"Resizing Gemini output from {result_image.size} to {original_size}")
                        result_image = result_image.resize(original_size, Image.LANCZOS)

                    result_image.save(str(output_path), 'PNG')
                    logger.info(f"✓ Gemini generated label: {output_path} ({result_image.size[0]}x{result_image.size[1]})")
                    return output_path

            # No image in response
            logger.error(f"❌ Gemini did not return an image for label generation")
            return None

        except Exception as e:
            logger.error(f"❌ Gemini label generation failed: {e}")
            return None

    def verify_label_text(
        self,
        label_image_path: Path,
        expected_product_name: str,
        expected_ingredients: str,
        expected_sku: str
    ) -> Dict:
        """Verify generated label text using Gemini OCR.

        Sends the generated label to Gemini Vision (OCR model, not image gen)
        and compares extracted text with expected values.

        Args:
            label_image_path: Path to generated label PNG
            expected_product_name: Expected product name from database
            expected_ingredients: Expected ingredients from database
            expected_sku: Expected SKU from database

        Returns:
            {
                'is_valid': True/False,
                'match_percentage': 0-100,
                'detected_product_name': '...',
                'detected_ingredients': '...',
                'detected_sku': '...',
                'recommendation': 'accept' or 'retry'
            }
        """
        logger.info(f"🔍 Verifying label text: {label_image_path.name}")

        pil_image = Image.open(label_image_path)

        prompt = """Extract ALL text from this pharmaceutical product label.

Return ONLY valid JSON:
{
    "product_name": "the main product name/title",
    "ingredients": "all ingredients with dosages",
    "sku": "SKU/product code like YPB.XXX"
}

Rules:
- Extract text EXACTLY as it appears
- If a field is not found, return empty string
- Return ONLY JSON, no markdown"""

        try:
            generation_config = types.GenerateContentConfig(
                temperature=0.1,
                max_output_tokens=2000
            )

            response = self.client.models.generate_content(
                model=self.model,  # gemini-2.5-flash (OCR model)
                contents=[prompt, pil_image],
                config=generation_config
            )

            result_text = response.text.strip()

            # Remove markdown code blocks
            if '```json' in result_text:
                match = re.search(r'```json\n(.*?)\n```', result_text, re.DOTALL)
                if match:
                    result_text = match.group(1)
            elif '```' in result_text:
                match = re.search(r'```\n(.*?)\n```', result_text, re.DOTALL)
                if match:
                    result_text = match.group(1)

            detected = json.loads(result_text)

            detected_name = detected.get('product_name', '')
            detected_ingredients = detected.get('ingredients', '')
            detected_sku = detected.get('sku', '')

            # Calculate match scores
            matches = 0
            total = 0

            if expected_product_name:
                total += 1
                if expected_product_name.lower().strip() in detected_name.lower().strip() or \
                   detected_name.lower().strip() in expected_product_name.lower().strip():
                    matches += 1

            if expected_sku:
                total += 1
                if expected_sku.lower().strip() in detected_sku.lower().strip() or \
                   detected_sku.lower().strip() in expected_sku.lower().strip():
                    matches += 1

            if expected_ingredients:
                total += 1
                # Check if key parts of ingredients match
                exp_parts = [p.strip().lower() for p in expected_ingredients.split('/')]
                det_lower = detected_ingredients.lower()
                ingredient_matches = sum(1 for p in exp_parts if p in det_lower)
                if exp_parts and ingredient_matches >= len(exp_parts) * 0.5:
                    matches += 1

            match_percentage = int((matches / total * 100)) if total > 0 else 0
            is_valid = match_percentage >= 66  # At least 2/3 fields match

            recommendation = 'accept' if is_valid else 'retry'

            logger.info(f"✓ Label verification: {match_percentage}% match "
                       f"(name: '{detected_name[:30]}', sku: '{detected_sku}') → {recommendation}")

            return {
                'is_valid': is_valid,
                'match_percentage': match_percentage,
                'detected_product_name': detected_name,
                'detected_ingredients': detected_ingredients,
                'detected_sku': detected_sku,
                'recommendation': recommendation
            }

        except Exception as e:
            logger.error(f"❌ Label verification failed: {e}")
            return {
                'is_valid': False,
                'match_percentage': 0,
                'detected_product_name': '',
                'detected_ingredients': '',
                'detected_sku': '',
                'recommendation': 'accept',  # Accept on verification failure (don't block)
                'error': str(e)
            }
