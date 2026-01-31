#!/usr/bin/env python3
"""Test script for asynchronous label generation"""

import requests
import time
import json
from pathlib import Path

BASE_URL = "http://localhost:8000"

def test_label_generation(limit=5):
    """Test label generation with specified product limit"""

    print(f"\n{'='*60}")
    print(f"🧪 TEST: Label Generation ({limit} products)")
    print(f"{'='*60}\n")

    # Prepare files
    template_path = Path("/tmp/test_template.svg")

    if not template_path.exists():
        print(f"❌ Template not found: {template_path}")
        return False

    # Prepare form data
    files = {
        'template': ('real_example.svg', open(template_path, 'rb'), 'image/svg+xml')
    }

    data = {
        'textAreas': json.dumps({}),  # Auto-detect from placeholders
        'limit': str(limit),
        'tracking_id': f'test_{int(time.time())}'
    }

    print("📤 Step 1: Sending request to /api/generate-labels-combined...")
    start_time = time.time()

    try:
        response = requests.post(
            f"{BASE_URL}/api/generate-labels-combined",
            files=files,
            data=data
        )

        request_time = time.time() - start_time
        print(f"   ⏱️  Response time: {request_time:.2f}s")

        if response.status_code != 200:
            print(f"   ❌ Error: HTTP {response.status_code}")
            print(f"   {response.text}")
            return False

        result = response.json()

        if not result.get('success'):
            print(f"   ❌ Error: {result.get('error')}")
            return False

        job_id = result.get('job_id')
        tracking_id = result.get('tracking_id')

        print(f"   ✅ Request successful!")
        print(f"   📋 Job ID: {job_id}")
        print(f"   📋 Tracking ID: {tracking_id}")
        print(f"   🎯 Status: {result.get('status')}")
        print(f"   💬 Message: {result.get('message')}")

        # Close file
        files['template'][1].close()

        # Poll for progress
        print(f"\n📊 Step 2: Polling progress...")
        print(f"   (Polling every 0.5s, max 120s)")

        poll_count = 0
        max_polls = 240  # 120 seconds

        while poll_count < max_polls:
            poll_count += 1
            time.sleep(0.5)

            try:
                progress_response = requests.get(
                    f"{BASE_URL}/api/generation-progress/{tracking_id}"
                )

                if progress_response.status_code == 200:
                    progress_data = progress_response.json()
                    status = progress_data.get('status')
                    percentage = progress_data.get('percentage', 0)
                    message = progress_data.get('message', '')
                    current = progress_data.get('current', 0)
                    total = progress_data.get('total', 0)

                    # Print progress (overwrite line)
                    progress_bar = "█" * int(percentage / 5) + "░" * (20 - int(percentage / 5))
                    print(f"\r   [{progress_bar}] {percentage}% - {message} ({current}/{total})", end='', flush=True)

                    if status == 'completed':
                        print()  # New line
                        print(f"   ✅ Generation completed!")
                        break
                    elif status == 'failed':
                        print()
                        print(f"   ❌ Generation failed: {message}")
                        return False

            except Exception as e:
                # Ignore polling errors
                pass

        if poll_count >= max_polls:
            print(f"\n   ⚠️  Timeout after {max_polls * 0.5}s")
            return False

        # Fetch results
        print(f"\n📥 Step 3: Fetching results from /api/generation-results/{job_id}...")

        results_response = requests.get(
            f"{BASE_URL}/api/generation-results/{job_id}"
        )

        if results_response.status_code != 200:
            print(f"   ❌ Error fetching results: HTTP {results_response.status_code}")
            print(f"   {results_response.text}")
            return False

        results_data = results_response.json()

        if not results_data.get('success'):
            print(f"   ❌ Error: {results_data.get('error')}")
            return False

        labels = results_data.get('labels', [])
        errors = results_data.get('errors', 0)
        zip_file = results_data.get('zip_file')

        print(f"   ✅ Results fetched successfully!")
        print(f"   📊 Labels generated: {len(labels)}")
        print(f"   ❌ Errors: {errors}")
        print(f"   📦 ZIP file: {zip_file}")

        # Show sample labels
        if labels:
            print(f"\n📋 Sample labels:")
            for i, label in enumerate(labels[:3]):
                sku = label.get('sku')
                product_name = label.get('product_name')
                formats = list(label.get('files', {}).keys())
                print(f"   {i+1}. {sku} - {product_name}")
                print(f"      Formats: {', '.join(formats)}")

        total_time = time.time() - start_time
        print(f"\n⏱️  Total time: {total_time:.2f}s")
        print(f"✅ TEST PASSED!\n")

        return True

    except Exception as e:
        print(f"\n❌ Exception: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    # Test 1: Small batch (5 products)
    success = test_label_generation(limit=5)

    if success:
        print("\n" + "="*60)
        print("🎉 ALL TESTS PASSED!")
        print("="*60)
    else:
        print("\n" + "="*60)
        print("❌ TEST FAILED!")
        print("="*60)
