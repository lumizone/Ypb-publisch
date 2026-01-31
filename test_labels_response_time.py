#!/usr/bin/env python3
"""Test labels endpoint response time"""

import requests
import time
from pathlib import Path

BASE_URL = "http://localhost:8000"

# Prepare request
files = {
    'template': ('template.svg', open(Path("/Users/lukasz/YPBv2/real_example.svg"), 'rb'), 'image/svg+xml')
}

data = {
    'limit': 5  # Just 5 products
}

print("\n" + "="*70)
print("⏱️  LABELS ENDPOINT RESPONSE TIME TEST")
print("="*70)
print(f"\nSending request to: {BASE_URL}/api/generate-labels-combined")
print(f"Products: 5")
print("\nMeasuring time to receive response...\n")

start_time = time.time()

try:
    response = requests.post(
        f"{BASE_URL}/api/generate-labels-combined",
        files=files,
        data=data,
        timeout=5  # Short timeout - should return immediately
    )

    response_time = time.time() - start_time

    # Close file
    files['template'][1].close()

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
        print(f"\n✅ LABELS ENDPOINT: ASYNC ({response_time:.3f}s)")
    else:
        print(f"\n❌ LABELS ENDPOINT: SLOW ({response_time:.3f}s)")

except requests.Timeout:
    response_time = time.time() - start_time
    print(f"\n❌ TIMEOUT after {response_time:.3f}s")
    print(f"   LABELS ENDPOINT is BLOCKING")

except Exception as e:
    response_time = time.time() - start_time
    print(f"\n❌ ERROR after {response_time:.3f}s")
    print(f"   {e}")

print("\n" + "="*70 + "\n")
