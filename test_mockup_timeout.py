#!/usr/bin/env python3
"""Test to demonstrate mockup generation timeout issue"""

import requests
import time
from pathlib import Path

BASE_URL = "http://localhost:8000"

def test_synchronous_mockup_timeout():
    """
    Test demonstrating timeout issue with synchronous mockup generation.
    This shows why we need async implementation.
    """

    print(f"\n{'='*70}")
    print(f"🧪 TEST: Synchronous Mockup Generation (Shows Timeout Problem)")
    print(f"{'='*70}\n")

    # Use existing labels from previous successful generation
    labels_dir = Path("/Users/lukasz/YPBv2/output/labels_20260131_002617")

    if not labels_dir.exists():
        print(f"❌ Labels directory not found: {labels_dir}")
        return False

    # Find some label files
    label_files = list(labels_dir.glob("label_*.png"))[:3]  # Just 3 labels for quick test

    if not label_files:
        print(f"❌ No label PNG files found in {labels_dir}")
        return False

    print(f"📋 Found {len(label_files)} label files")
    print(f"   Using labels: {[f.name for f in label_files]}")

    # We need a vial image - check if exists
    vial_path = Path("/Users/lukasz/YPBv2/green background.png")
    if not vial_path.exists():
        print(f"❌ Vial image not found: {vial_path}")
        # Try to find any image
        vial_candidates = list(Path("/Users/lukasz/YPBv2").glob("*.png"))[:1]
        if vial_candidates:
            vial_path = vial_candidates[0]
            print(f"   Using alternative: {vial_path}")
        else:
            return False

    print(f"\n⏱️  Testing with SHORT timeout (10 seconds)...")
    print(f"   Expected: Request will TIMEOUT before completion")
    print(f"   (Simulates what happens when you switch browser tab)\n")

    # Prepare request (we'll use single mockup endpoint for quick demo)
    print(f"📤 Sending request to /api/generate-single-mockup...")
    print(f"   Timeout: 10 seconds")
    print(f"   (Normal generation takes ~30s per mockup)")

    start_time = time.time()

    try:
        files = {
            'vial': ('vial.png', open(vial_path, 'rb'), 'image/png'),
            'label': ('label.png', open(label_files[0], 'rb'), 'image/png')
        }

        data = {
            'productName': '4X Blend',
            'sku': 'YPB.100',
            'dosage': 'Test Dosage'
        }

        response = requests.post(
            f"{BASE_URL}/api/generate-single-mockup",
            files=files,
            data=data,
            timeout=10  # 10 second timeout
        )

        elapsed = time.time() - start_time

        # Close files
        files['vial'][1].close()
        files['label'][1].close()

        if response.status_code != 200:
            print(f"\n   ❌ Request failed: HTTP {response.status_code}")
            print(f"   Response: {response.text}")
            return False

        print(f"\n   ✅ Request completed in {elapsed:.2f}s")
        print(f"   (This is unexpected! Should have timed out)")

        return True

    except requests.Timeout:
        elapsed = time.time() - start_time
        print(f"\n   ⏱️  REQUEST TIMED OUT after {elapsed:.2f}s")
        print(f"\n{'='*70}")
        print(f"❌ PROBLEM DEMONSTRATED:")
        print(f"{'='*70}")
        print(f"When browser timeout occurs (tab switching, long operation):")
        print(f"  1. HTTP request is cancelled")
        print(f"  2. User sees error or 'loading forever'")
        print(f"  3. Server may still be processing (wasting resources)")
        print(f"  4. No way to resume or check results")
        print(f"\n🔧 SOLUTION: Asynchronous processing with background tasks")
        print(f"  1. Request returns immediately with job_id")
        print(f"  2. Processing continues in background")
        print(f"  3. Frontend polls for progress")
        print(f"  4. Can switch tabs, close browser - still works!")
        print(f"{'='*70}\n")

        return False

    except Exception as e:
        elapsed = time.time() - start_time
        print(f"\n   ❌ Error after {elapsed:.2f}s: {e}")
        return False


if __name__ == "__main__":
    test_synchronous_mockup_timeout()
