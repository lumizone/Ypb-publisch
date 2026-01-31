"""
Test script for side-by-side verification.
Tests the new verification system with sample images.
"""

import sys
from pathlib import Path
import PIL.Image

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from verification_side_by_side import (
    create_mockup_vs_label_comparison,
    verify_mockup_with_sidebyside
)
import config


def test_comparison_image_creation():
    """Test 1: Check if comparison image is created correctly"""
    print("=" * 80)
    print("TEST 1: Comparison Image Creation")
    print("=" * 80)

    # Create mock images for testing
    mockup = PIL.Image.new('RGB', (800, 1000), (255, 255, 255))
    label = PIL.Image.new('RGB', (400, 600), (255, 255, 255))

    # Add some text to images (mock)
    from PIL import ImageDraw, ImageFont
    draw_mockup = ImageDraw.Draw(mockup)
    draw_label = ImageDraw.Draw(label)

    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 40)
    except:
        font = ImageFont.load_default()

    draw_mockup.text((300, 400), "4X Blend", fill=(0, 0, 0), font=font)
    draw_mockup.text((300, 450), "YPB.100", fill=(0, 0, 0), font=font)

    draw_label.text((100, 200), "4X Blend", fill=(0, 0, 0), font=font)
    draw_label.text((100, 250), "YPB.100", fill=(0, 0, 0), font=font)

    # Create comparison
    comparison = create_mockup_vs_label_comparison(mockup, label, sku="YPB.100")

    print(f"✓ Comparison image created: {comparison.size}")
    print(f"  Width: {comparison.width}px")
    print(f"  Height: {comparison.height}px")
    print(f"  Mode: {comparison.mode}")

    # Save for inspection
    output_path = Path(__file__).parent / "test_comparison.png"
    comparison.save(output_path)
    print(f"✓ Saved to: {output_path}")
    print()

    return comparison


def test_verification_with_real_files():
    """Test 2: Verify with real files if available"""
    print("=" * 80)
    print("TEST 2: Verification with Real Files (if available)")
    print("=" * 80)

    # Check for sample files in output directory
    output_dir = config.OUTPUT_DIR

    # Look for recent mockup and label
    mockup_dirs = sorted(output_dir.glob("mockups_*"), reverse=True)
    label_dirs = sorted(output_dir.glob("labels_*"), reverse=True)

    if not mockup_dirs or not label_dirs:
        print("⚠ No sample files found in output directory")
        print("  Generate some mockups first to test verification")
        print()
        return None

    mockup_dir = mockup_dirs[0]
    label_dir = label_dirs[0]

    print(f"Using mockup dir: {mockup_dir.name}")
    print(f"Using label dir: {label_dir.name}")

    # Find first mockup and corresponding label
    mockup_files = list(mockup_dir.glob("mockup_*.png"))

    if not mockup_files:
        print("⚠ No mockup files found")
        return None

    mockup_file = mockup_files[0]
    print(f"Mockup: {mockup_file.name}")

    # Extract SKU from filename
    # Format: mockup_YPB.100.png
    import re
    match = re.search(r'mockup_([A-Z]+\.\d+)\.png', mockup_file.name)
    if not match:
        print("⚠ Could not extract SKU from filename")
        return None

    sku = match.group(1)
    print(f"SKU: {sku}")

    # Find corresponding label
    label_file = label_dir / f"label_{sku}.png"
    if not label_file.exists():
        # Try other formats
        label_file = label_dir / f"label_{sku}.jpg"

    if not label_file.exists():
        print(f"⚠ Label file not found for SKU {sku}")
        return None

    print(f"Label: {label_file.name}")

    # Load images
    mockup_image = PIL.Image.open(mockup_file)
    label_image = PIL.Image.open(label_file)

    print(f"\nMockup size: {mockup_image.size}")
    print(f"Label size: {label_image.size}")

    # Verify (requires GEMINI_API_KEY)
    if not config.GEMINI_API_KEY:
        print("\n⚠ GEMINI_API_KEY not configured")
        print("  Skipping actual verification")
        print()
        return None

    print("\n🔍 Running verification...")

    result = verify_mockup_with_sidebyside(
        mockup_image,
        label_image,
        expected_sku=sku,
        expected_product_name="Test Product",
        expected_dosage="5mg",
        api_key=config.GEMINI_API_KEY
    )

    print("\n📊 VERIFICATION RESULTS:")
    print(f"  ✓ Valid: {result['is_valid']}")
    print(f"  ✓ Match: {result['match_percentage']}%")
    print(f"  ✓ Text Accurate: {result['text_accurate']}")
    print(f"  ✓ Visually Identical: {result['visually_identical']}")
    print(f"  ✓ Text Readable: {result['text_readable']}")
    print(f"  ✓ No Deformation: {result['no_deformation']}")
    print(f"  ✓ Recommendation: {result['recommendation']}")
    print(f"  ✓ Confidence: {result['confidence']:.2f}")

    if result['differences']:
        print(f"\n  Differences found ({len(result['differences'])}):")
        for diff in result['differences'][:5]:  # Show first 5
            print(f"    - {diff}")

    print()
    return result


def main():
    """Run all tests"""
    print("\n" + "=" * 80)
    print("SIDE-BY-SIDE VERIFICATION TEST SUITE")
    print("=" * 80 + "\n")

    # Test 1: Basic functionality
    comparison = test_comparison_image_creation()

    # Test 2: Real verification (if files available)
    result = test_verification_with_real_files()

    print("=" * 80)
    print("ALL TESTS COMPLETED")
    print("=" * 80)

    if comparison:
        print("✓ Comparison image creation: PASSED")

    if result:
        print("✓ Real verification: PASSED")
        print(f"  Final result: {'ACCEPT' if result['is_valid'] else 'REJECT'}")

    print()


if __name__ == "__main__":
    main()
