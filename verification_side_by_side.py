"""
Side-by-side verification module for mockup quality validation.
Compares full mockup (vial with label) against reference label.
"""

import logging
from pathlib import Path
from io import BytesIO
import base64
import json

import PIL.Image
from PIL import ImageDraw, ImageFont

logger = logging.getLogger(__name__)


def create_mockup_vs_label_comparison(mockup_image, label_reference, sku=""):
    """
    Creates side-by-side comparison: [Full Mockup] | [Reference Label]

    This shows:
    - LEFT: Complete mockup (vial with label applied)
    - RIGHT: Original flat label design

    Purpose: Vision API can verify that the label on the mockup matches
    the reference label in terms of text, colors, fonts, and readability.

    Args:
        mockup_image: PIL Image of generated mockup (vial with label)
        label_reference: PIL Image of original label design (flat)
        sku: Optional SKU for labeling

    Returns:
        PIL Image showing [Mockup | Label] comparison
    """

    # Target height for both sides (larger for better Vision API analysis)
    target_height = 800

    # DEBUG: Log mockup mode before processing
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"[VERIFICATION] Mockup mode BEFORE resize: {mockup_image.mode}, size: {mockup_image.size}")

    # Resize mockup maintaining aspect ratio
    mockup_ratio = target_height / mockup_image.height
    mockup_resized = mockup_image.resize(
        (int(mockup_image.width * mockup_ratio), target_height),
        PIL.Image.Resampling.LANCZOS
    )

    logger.info(f"[VERIFICATION] Mockup mode AFTER resize: {mockup_resized.mode}")

    # Convert mockup to RGB (preserve colors)
    if mockup_resized.mode == 'RGBA':
        # Composite onto white background
        mockup_with_bg = PIL.Image.new('RGB', mockup_resized.size, (255, 255, 255))
        mockup_with_bg.paste(mockup_resized, (0, 0), mockup_resized)
        mockup_resized = mockup_with_bg
        logger.info(f"[VERIFICATION] Converted RGBA mockup to RGB with white background")
    elif mockup_resized.mode != 'RGB':
        mockup_resized = mockup_resized.convert('RGB')
        logger.info(f"[VERIFICATION] Converted {mockup_resized.mode} mockup to RGB")

    # Resize label maintaining aspect ratio
    label_ratio = target_height / label_reference.height
    label_resized = label_reference.resize(
        (int(label_reference.width * label_ratio), target_height),
        PIL.Image.Resampling.LANCZOS
    )

    # CRITICAL FIX: Convert label to RGB with WHITE background
    # Labels are generated with transparent background (RGBA mode)
    # This causes Vision API to see label without proper context
    if label_resized.mode == 'RGBA':
        # Create white background
        label_with_bg = PIL.Image.new('RGB', label_resized.size, (255, 255, 255))
        # Paste label with alpha compositing
        label_with_bg.paste(label_resized, (0, 0), label_resized)
        label_resized = label_with_bg
    elif label_resized.mode != 'RGB':
        # Convert any other mode to RGB
        label_resized = label_resized.convert('RGB')

    # Create composite with gap between images
    gap = 80  # Wider gap for clear separation
    header_height = 120
    total_width = mockup_resized.width + gap + label_resized.width
    total_height = target_height + header_height

    # White background
    composite = PIL.Image.new('RGB', (total_width, total_height), (255, 255, 255))

    # Paste images
    composite.paste(mockup_resized, (0, header_height))
    composite.paste(label_resized, (mockup_resized.width + gap, header_height))

    # Add headers and labels
    draw = ImageDraw.Draw(composite)

    # Try to load system font, fallback to default
    try:
        font_title = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 32)
        font_label = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 20)
        font_sku = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 16)
    except Exception:
        font_title = ImageFont.load_default()
        font_label = font_title
        font_sku = font_title

    # Left header: "GENERATED MOCKUP"
    draw.text(
        (20, 20),
        "GENERATED MOCKUP",
        fill=(220, 50, 50),  # Red
        font=font_title
    )
    draw.text(
        (20, 60),
        "(Vial with label applied)",
        fill=(100, 100, 100),  # Gray
        font=font_label
    )

    # Right header: "REFERENCE LABEL"
    draw.text(
        (mockup_resized.width + gap + 20, 20),
        "REFERENCE LABEL",
        fill=(50, 150, 50),  # Green
        font=font_title
    )
    draw.text(
        (mockup_resized.width + gap + 20, 60),
        "(Original design - flat)",
        fill=(100, 100, 100),  # Gray
        font=font_label
    )

    # SKU label at top center
    if sku:
        sku_text = f"SKU: {sku}"
        # Center the SKU text
        bbox = draw.textbbox((0, 0), sku_text, font=font_sku)
        text_width = bbox[2] - bbox[0]
        draw.text(
            ((total_width - text_width) // 2, 95),
            sku_text,
            fill=(50, 50, 50),
            font=font_sku
        )

    # Vertical divider line
    line_x = mockup_resized.width + gap // 2
    draw.line(
        [(line_x, 0), (line_x, total_height)],
        fill=(200, 200, 200),
        width=3
    )

    # Horizontal divider line (separating header from images)
    draw.line(
        [(0, header_height - 5), (total_width, header_height - 5)],
        fill=(200, 200, 200),
        width=2
    )

    logger.info(f"Created mockup vs label comparison: {total_width}x{total_height}")
    return composite


def verify_mockup_with_sidebyside(mockup_image, label_reference, expected_sku,
                                   expected_product_name, expected_dosage, api_key):
    """
    Verify mockup quality using side-by-side comparison with Gemini Vision API.

    Compares:
    - LEFT: Generated mockup (vial with label)
    - RIGHT: Reference label (original design)

    Checks:
    1. Text accuracy: Does label on mockup have same text as reference?
    2. Visual fidelity: Same colors, fonts, layout?
    3. Readability: Is text on mockup sharp and clear?
    4. Deformation: Is text distorted or warped unnaturally?

    Args:
        mockup_image: PIL Image of generated mockup
        label_reference: PIL Image of reference label
        expected_sku: Expected SKU string
        expected_product_name: Expected product name
        expected_dosage: Expected dosage/ingredients
        api_key: Gemini API key

    Returns:
        dict with verification results:
        {
            'is_valid': bool,
            'match_percentage': int (0-100),
            'text_accurate': bool,
            'visually_identical': bool,
            'text_readable': bool,
            'no_deformation': bool,
            'detected_sku': str,
            'detected_product_name': str,
            'detected_dosage': str,
            'differences': List[str],
            'recommendation': str ('accept'/'retry'/'reject'),
            'confidence': float (0.0-1.0)
        }
    """
    import requests

    try:
        # Create side-by-side comparison image
        comparison_image = create_mockup_vs_label_comparison(
            mockup_image,
            label_reference,
            sku=expected_sku
        )

        # Convert to base64
        buffered = BytesIO()
        comparison_image.save(buffered, format="PNG")
        comparison_base64 = base64.b64encode(buffered.getvalue()).decode('utf-8')

        # Comprehensive prompt for Vision API
        prompt = f"""You are analyzing a pharmaceutical vial mockup for QUALITY CONTROL.

You see TWO images side-by-side:

LEFT IMAGE: Generated mockup showing a vial with a label applied
RIGHT IMAGE: Reference label design (the original flat label that should appear on the vial)

EXPECTED VALUES (from database):
- Product Name: "{expected_product_name}"
- SKU: "{expected_sku}"
- Dosage/Ingredients: "{expected_dosage}"

YOUR TASK: Verify that the label on the mockup (LEFT) accurately reproduces the reference label (RIGHT).

ANALYZE THESE CRITICAL ASPECTS:

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. TEXT ACCURACY ✓
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Compare the TEXT on the mockup label (left) with the reference label (right):

IMPORTANT - LABEL WRAPPING BEHAVIOR:
⚠️ Labels on cylindrical vials WRAP AROUND the surface
⚠️ Text at LEFT/RIGHT edges may be PARTIALLY VISIBLE or CUT OFF
⚠️ This is NORMAL and ACCEPTABLE for vial mockups
⚠️ Do NOT penalize for edge cropping - this is expected behavior

For VISIBLE TEXT (not at edges):
✓ Is every word spelled IDENTICALLY?
✓ Are all numbers EXACTLY the same?
✓ Is punctuation preserved? (commas, slashes, parentheses, periods, hyphens)
✓ Are units present? (mg, mcg, ml, etc.)

For EDGE TEXT (at left/right borders):
✓ Partial SKU is OK: "YPB.1" when full is "YPB.111" - ACCEPTABLE
✓ Partial words are OK: "RESEARCH USE" when full is "RESEARCH USE ONLY" - ACCEPTABLE
✓ Cut-off text is OK: Text disappearing at edges due to wrapping - ACCEPTABLE

Examples of REAL FAILURES (ignore edge cropping):
❌ "GHRP-2 (5mg)" vs "GHRP-2 5mg" - missing parentheses (CENTER text)
❌ "4X Blend" vs "4X Bleend" - typo (CENTER text)
❌ Missing ingredient lines (CENTER text)

Examples of ACCEPTABLE (edge cropping):
✅ "YPB.111" vs "YPB.1" - partial SKU at edge (ACCEPTABLE)
✅ "RESEARCH USE ONLY" vs "RESEARCH USE" - partial text at edge (ACCEPTABLE)
✅ "10mg" vs "10 mg" - spacing variation (ACCEPTABLE)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
2. VISUAL FIDELITY ✓
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Compare the APPEARANCE:

✓ Are text colors the same? (black/white/gray/colored text)
✓ Are background colors the same?
✓ Is font family similar? (serif/sans-serif, script/monospace)
✓ Is font size proportional? (relative sizes match)
✓ Is layout similar? (alignment, spacing, positioning)

✓ FONT WEIGHT CHECK:
  • Is SKU bold on reference? → Should be bold on mockup
  • Is product name bold on reference? → Should be bold on mockup
  • Compare font weight (bold vs regular)

Examples of FAILURES:
❌ Black text on left, blue text on right - color mismatch
❌ Arial font on left, Times New Roman on right - font mismatch
❌ Bold text on left, regular text on right - weight mismatch
❌ Centered on left, left-aligned on right - alignment mismatch

**IMPORTANT:** Font weight mismatches (bold vs regular) are MAJOR visual differences and should be flagged clearly in the differences list.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
3. READABILITY ON MOCKUP ✓
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Focus on the MOCKUP (left image) ONLY:

✓ Is the text SHARP and CLEAR?
✓ Can you read all text easily?
✓ Is the text resolution high enough?
✓ Are there any blurry areas?
✓ Is the contrast sufficient (text vs background)?
✓ Are small details visible (dots, commas, thin lines)?

Examples of FAILURES:
❌ Text is blurry or pixelated
❌ Text is too small to read clearly
❌ Low contrast makes text hard to distinguish
❌ Compression artifacts around text
❌ Text appears out of focus

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
4. NATURAL DEFORMATION CHECK ✓
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Assess if text on the mockup has NATURAL vs UNNATURAL deformation:

NATURAL (ACCEPTABLE):
✓ Slight curvature following the vial's cylindrical shape
✓ Mild perspective distortion (top/bottom of vial)
✓ Natural lighting/shadow effects
✓ Realistic wrapping around curved surface

UNNATURAL (UNACCEPTABLE):
❌ Text is stretched or squashed disproportionately
❌ Text appears warped or melted
❌ Letters are irregularly sized or spaced
❌ Text baseline is wavy or distorted
❌ Text appears to be "painted on" instead of following vial surface
❌ Unnatural perspective that doesn't match vial geometry

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
VERIFICATION STANDARDS (UPDATED FOR VIAL WRAPPING):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

⚠️ CRITICAL: Ignore edge cropping when evaluating text accuracy!
⚠️ Partial SKU, partial "RESEARCH USE ONLY", spacing variations = ACCEPTABLE

ACCEPT if:
- Center text accuracy: 100% (main text identical, ignore edge cropping)
- Edge text: Can be partial/cut (this is expected for wrapped labels)
- Visual fidelity: ≥85% (colors/fonts similar)
- Readability: Clear and sharp
- Deformation: Natural only

RETRY if:
- Center text has 1-2 minor differences (punctuation, spacing)
- Visual fidelity: 70-84% (some color/font differences)
- Readability: Slightly blurry but readable
- Deformation: Mild unnatural distortion

REJECT if:
- Center text accuracy: <90% (wrong words, missing main content)
- Visual fidelity: <70% (major color/font differences)
- Readability: Blurry, pixelated, or unreadable
- Deformation: Severe warping or distortion

EXAMPLES OF ACCEPTABLE EDGE VARIATIONS:
✅ SKU partial: "YPB.1" when database has "YPB.111"
✅ Text partial: "RESEARCH USE" when full is "RESEARCH USE ONLY"
✅ Spacing: "10 mg" vs "10mg"
✅ Cut-off at wrapping point: Normal for cylindrical vials

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Return ONLY valid JSON (no markdown code blocks):

{{
    "text_analysis": {{
        "detected_product_name": "exact text from mockup",
        "detected_sku": "exact text from mockup",
        "detected_dosage": "exact text from mockup",
        "all_text_identical": true/false,
        "text_differences": ["list each difference found"],
        "text_accuracy_percentage": 0-100
    }},

    "visual_analysis": {{
        "colors_match": true/false,
        "fonts_match": true/false,
        "layout_match": true/false,
        "visual_differences": ["list visual differences"],
        "visual_fidelity_percentage": 0-100
    }},

    "readability_analysis": {{
        "text_is_sharp": true/false,
        "text_is_clear": true/false,
        "sufficient_contrast": true/false,
        "all_text_readable": true/false,
        "readability_issues": ["list any readability problems"],
        "readability_score": 0-100
    }},

    "deformation_analysis": {{
        "has_natural_curvature": true/false,
        "has_unnatural_distortion": true/false,
        "text_properly_wrapped": true/false,
        "deformation_issues": ["list any unnatural deformations"],
        "deformation_acceptable": true/false
    }},

    "overall_assessment": {{
        "match_percentage": 0-100,
        "is_acceptable": true/false,
        "recommendation": "accept/retry/reject",
        "confidence": 0.0-1.0,
        "severity": "none/minor/major/critical",
        "summary": "brief explanation of decision"
    }}
}}

Be EXTREMELY DETAILED and OBJECTIVE. List EVERY difference found, no matter how small."""

        # Call Gemini Vision API
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"

        payload = {
            "contents": [{
                "parts": [
                    {"text": prompt},
                    {
                        "inline_data": {
                            "mime_type": "image/png",
                            "data": comparison_base64
                        }
                    }
                ]
            }],
            "generationConfig": {
                "temperature": 0.1,  # Low temperature for consistent analysis
                "topP": 0.95,
                "topK": 40
            }
        }

        headers = {"Content-Type": "application/json"}

        logger.info(f"Verifying mockup with side-by-side comparison - SKU={expected_sku}")
        response = requests.post(url, headers=headers, json=payload, timeout=60)
        response.raise_for_status()
        response_data = response.json()

        # Extract text response
        verification_text = ""
        if 'candidates' in response_data and len(response_data['candidates']) > 0:
            candidate = response_data['candidates'][0]
            if 'content' in candidate and 'parts' in candidate['content']:
                for part in candidate['content']['parts']:
                    if 'text' in part:
                        verification_text = part['text']
                        break

        if not verification_text:
            logger.error("Vision API returned no text response")
            return {
                'is_valid': False,
                'match_percentage': 0,
                'text_accurate': False,
                'visually_identical': False,
                'text_readable': False,
                'no_deformation': False,
                'detected_sku': '',
                'detected_product_name': '',
                'detected_dosage': '',
                'differences': ['Vision API failed to respond'],
                'recommendation': 'reject',
                'confidence': 0.0
            }

        # Clean markdown formatting
        verification_text = verification_text.strip()
        if verification_text.startswith('```json'):
            verification_text = verification_text[7:]
        if verification_text.startswith('```'):
            verification_text = verification_text[3:]
        if verification_text.endswith('```'):
            verification_text = verification_text[:-3]
        verification_text = verification_text.strip()

        # Parse JSON
        try:
            analysis = json.loads(verification_text)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Vision API JSON: {e}")
            logger.error(f"Response text: {verification_text[:500]}")
            return {
                'is_valid': False,
                'match_percentage': 0,
                'text_accurate': False,
                'visually_identical': False,
                'text_readable': False,
                'no_deformation': False,
                'detected_sku': '',
                'detected_product_name': '',
                'detected_dosage': '',
                'differences': [f'JSON parse error: {str(e)}'],
                'recommendation': 'reject',
                'confidence': 0.0
            }

        # Extract nested results
        text_analysis = analysis.get('text_analysis', {})
        visual_analysis = analysis.get('visual_analysis', {})
        readability_analysis = analysis.get('readability_analysis', {})
        deformation_analysis = analysis.get('deformation_analysis', {})
        overall = analysis.get('overall_assessment', {})

        # Build comprehensive result
        result = {
            'is_valid': overall.get('is_acceptable', False),
            'match_percentage': overall.get('match_percentage', 0),

            # Component scores
            'text_accurate': text_analysis.get('all_text_identical', False),
            'visually_identical': (
                visual_analysis.get('colors_match', False) and
                visual_analysis.get('fonts_match', False) and
                visual_analysis.get('layout_match', False)
            ),
            'text_readable': readability_analysis.get('all_text_readable', False),
            'no_deformation': deformation_analysis.get('deformation_acceptable', True),

            # Detected values
            'detected_sku': text_analysis.get('detected_sku', ''),
            'detected_product_name': text_analysis.get('detected_product_name', ''),
            'detected_dosage': text_analysis.get('detected_dosage', ''),

            # Differences
            'differences': (
                text_analysis.get('text_differences', []) +
                visual_analysis.get('visual_differences', []) +
                readability_analysis.get('readability_issues', []) +
                deformation_analysis.get('deformation_issues', [])
            ),

            # Decision
            'recommendation': overall.get('recommendation', 'unknown'),
            'confidence': overall.get('confidence', 0.0),
            'severity': overall.get('severity', 'unknown'),
            'summary': overall.get('summary', ''),

            # Full analysis for debugging
            'full_analysis': analysis
        }

        logger.info(
            f"Side-by-side verification complete: "
            f"valid={result['is_valid']}, "
            f"match={result['match_percentage']}%, "
            f"recommendation={result['recommendation']}, "
            f"confidence={result['confidence']:.2f}"
        )

        return result

    except Exception as e:
        logger.error(f"Error in side-by-side verification: {e}", exc_info=True)
        return {
            'is_valid': False,
            'match_percentage': 0,
            'text_accurate': False,
            'visually_identical': False,
            'text_readable': False,
            'no_deformation': False,
            'detected_sku': '',
            'detected_product_name': '',
            'detected_dosage': '',
            'differences': [f'Verification error: {str(e)}'],
            'recommendation': 'reject',
            'confidence': 0.0
        }
