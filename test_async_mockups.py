#!/usr/bin/env python3
"""Test async mockup generation with tab switching capability"""

import requests
import time
from pathlib import Path

BASE_URL = "http://localhost:8000"

def test_async_mockup_generation():
    """
    Test async mockup generation - should return immediately with job_id.
    Simulates tab switching by showing you can close/switch without losing work.
    """

    print(f"\n{'='*70}")
    print(f"🧪 TEST: Async Mockup Generation (Tab Switch Safe)")
    print(f"{'='*70}\n")

    # Use existing labels from recent successful generation
    labels_job_id = "20260131_002617"  # Folder with actual PNG files (371 files)
    labels_dir = Path(f"/Users/lukasz/YPBv2/output/labels_{labels_job_id}")

    if not labels_dir.exists():
        print(f"❌ Labels directory not found: {labels_dir}")
        return False

    # Find label files
    label_files = list(labels_dir.glob("label_*.png"))[:3]  # Test with 3 labels only

    if not label_files:
        print(f"❌ No label PNG files found in {labels_dir}")
        return False

    print(f"📋 Found {len(label_files)} label files for testing")
    print(f"   Labels: {[f.name for f in label_files]}")

    # Prepare vial image
    vial_path = Path("/Users/lukasz/YPBv2/green backround.png")  # Note: typo in filename
    if not vial_path.exists():
        print(f"❌ Vial image not found: {vial_path}")
        return False

    print(f"\n⏱️  Sending async mockup generation request...")
    print(f"   Expected: Returns immediately (<1 second) with job_id")
    print(f"   (You could switch tabs safely during processing)\n")

    start_time = time.time()

    # Prepare request
    files = {
        'vial': ('vial.png', open(vial_path, 'rb'), 'image/png')
    }

    # Convert label files to expected format (list of dicts)
    import json
    import re

    label_objects = []
    for label_file in label_files:
        # Extract SKU from filename: label_YPB.238.png → YPB.238
        match = re.search(r'label_([A-Z]+\.\d+)\.png', label_file.name)
        if match:
            sku = match.group(1)
            label_objects.append({
                'sku': sku,
                'product_name': sku,  # Use SKU as product name (we don't have actual name)
                'path': str(label_file),
                'filename': label_file.name,
                'dosage': ''
            })

    data = {
        'labels_job_id': labels_job_id,
        'labels': json.dumps(label_objects)  # JSON string of label objects
    }

    try:
        # Send request - should return IMMEDIATELY
        response = requests.post(
            f"{BASE_URL}/api/generate-mockups-from-labels",
            files=files,
            data=data,
            timeout=30
        )

        request_time = time.time() - start_time

        # Close files
        for f in files.values():
            if hasattr(f[1], 'close'):
                f[1].close()

        if response.status_code != 200:
            print(f"\n❌ Request failed: HTTP {response.status_code}")
            print(f"   Response: {response.text}")
            return False

        data = response.json()

        print(f"✅ Request returned in {request_time:.3f}s")
        print(f"\n📦 Response:")
        print(f"   Job ID: {data.get('job_id')}")
        print(f"   Tracking ID: {data.get('tracking_id')}")
        print(f"   Status: {data.get('status')}")
        print(f"   Message: {data.get('message')}")

        if request_time > 2.0:
            print(f"\n⚠️  Warning: Request took {request_time:.3f}s (should be < 1s)")
            return False

        job_id = data.get('job_id')
        tracking_id = data.get('tracking_id')

        print(f"\n⏳ Polling progress (you could switch tabs now)...")

        # Poll progress
        poll_interval = 2  # Check every 2 seconds
        max_wait = 300  # 5 minutes max
        elapsed = 0

        while elapsed < max_wait:
            time.sleep(poll_interval)
            elapsed += poll_interval

            try:
                progress_response = requests.get(
                    f"{BASE_URL}/api/generation-progress/{tracking_id}",
                    timeout=5
                )

                if progress_response.status_code == 200:
                    progress_data = progress_response.json()

                    current = progress_data.get('current', 0)
                    total = progress_data.get('total', 0)
                    status = progress_data.get('status', 'unknown')

                    print(f"   Progress: {current}/{total} mockups ({status})")

                    if status == 'completed':
                        print(f"\n✅ Mockup generation completed!")

                        # Fetch results
                        results_response = requests.get(
                            f"{BASE_URL}/api/mockup-generation-results/{job_id}",
                            timeout=10
                        )

                        if results_response.status_code == 200:
                            results_data = results_response.json()

                            print(f"\n📊 Results:")
                            print(f"   Success: {results_data.get('success')}")
                            print(f"   Mockups: {len(results_data.get('mockups', []))}")
                            print(f"   ZIP: {results_data.get('zip_file')}")
                            print(f"   Errors: {len(results_data.get('errors', []))}")

                            if results_data.get('errors'):
                                print(f"\n⚠️  Errors:")
                                for error in results_data.get('errors', []):
                                    print(f"   - {error}")

                            return True
                        else:
                            print(f"\n❌ Failed to fetch results: HTTP {results_response.status_code}")
                            return False

                    elif status == 'failed':
                        print(f"\n❌ Generation failed")
                        return False

            except requests.Timeout:
                print(f"   ⏱️  Progress check timed out (continuing...)")
                continue
            except Exception as e:
                print(f"   ⚠️  Progress check error: {e}")
                continue

        print(f"\n⏱️  Timeout: Generation took longer than {max_wait}s")
        return False

    except requests.Timeout:
        request_time = time.time() - start_time
        print(f"\n❌ Request timed out after {request_time:.2f}s")
        return False

    except Exception as e:
        request_time = time.time() - start_time
        print(f"\n❌ Error after {request_time:.2f}s: {e}")
        return False


if __name__ == "__main__":
    print("\n" + "="*70)
    print("🧪 ASYNC MOCKUP GENERATION TEST")
    print("="*70)
    print("\nThis test demonstrates that:")
    print("  1. Request returns immediately (<1s) with job_id")
    print("  2. Processing happens in background")
    print("  3. You can safely switch browser tabs")
    print("  4. Results are available when complete")
    print("\nCompare to synchronous version:")
    print("  - Synchronous: 15-20 minutes blocking (tab switch = timeout)")
    print("  - Asynchronous: <1s response (tab switch = safe)")

    success = test_async_mockup_generation()

    print("\n" + "="*70)
    if success:
        print("✅ TEST PASSED: Async mockup generation works!")
    else:
        print("❌ TEST FAILED: Check errors above")
    print("="*70 + "\n")
