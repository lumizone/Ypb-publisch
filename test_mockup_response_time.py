#!/usr/bin/env python3
"""Simple test to measure endpoint response time"""

import requests
import time
import json
import re
from pathlib import Path

BASE_URL = "http://localhost:8000"

# Use existing labels
labels_job_id = "20260131_002617"
labels_dir = Path(f"/Users/lukasz/YPBv2/output/labels_{labels_job_id}")
label_files = list(labels_dir.glob("label_*.png"))[:1]  # Just 1 label for fast test

# Prepare label objects
label_objects = []
for label_file in label_files:
    match = re.search(r'label_([A-Z]+\.\d+)\.png', label_file.name)
    if match:
        sku = match.group(1)
        label_objects.append({
            'sku': sku,
            'product_name': sku,
            'path': str(label_file),
            'filename': label_file.name,
            'dosage': ''
        })

# Prepare request
files = {
    'vial': ('vial.png', open(Path("/Users/lukasz/YPBv2/green backround.png"), 'rb'), 'image/png')
}

data = {
    'labels_job_id': labels_job_id,
    'labels': json.dumps(label_objects)
}

print("\n" + "="*70)
print("⏱️  RESPONSE TIME TEST")
print("="*70)
print(f"\nSending request to: {BASE_URL}/api/generate-mockups-from-labels")
print(f"Labels: {len(label_objects)}")
print("\nMeasuring time to receive response...\n")

start_time = time.time()

try:
    response = requests.post(
        f"{BASE_URL}/api/generate-mockups-from-labels",
        files=files,
        data=data,
        timeout=5  # Short timeout - should return immediately
    )

    response_time = time.time() - start_time

    # Close file
    files['vial'][1].close()

    print(f"✅ Response received in: {response_time:.3f}s")
    print(f"   HTTP Status: {response.status_code}")

    if response.status_code == 200:
        data = response.json()
        print(f"\n📦 Response data:")
        print(f"   Success: {data.get('success')}")
        print(f"   Job ID: {data.get('job_id')}")
        print(f"   Status: {data.get('status')}")
        print(f"   Message: {data.get('message')}")

    if response_time < 2.0:
        print(f"\n✅ SUCCESS: Endpoint returns IMMEDIATELY ({response_time:.3f}s)")
        print(f"   This means async implementation is WORKING!")
    else:
        print(f"\n❌ FAILURE: Endpoint is SLOW ({response_time:.3f}s)")
        print(f"   This means it's still synchronous!")

except requests.Timeout:
    response_time = time.time() - start_time
    print(f"\n❌ TIMEOUT after {response_time:.3f}s")
    print(f"   Endpoint did NOT return response")
    print(f"   This means it's BLOCKING (synchronous)")

except Exception as e:
    response_time = time.time() - start_time
    print(f"\n❌ ERROR after {response_time:.3f}s")
    print(f"   {e}")

print("\n" + "="*70 + "\n")
