#!/usr/bin/env python3
"""Test Gemini API mockup generation to debug 400 error"""

import requests
import json
import base64
from PIL import Image
from io import BytesIO
import os
from dotenv import load_dotenv

load_dotenv('.env.local')

# Create simple test images
def create_test_image(color, size=(512, 512)):
    """Create a simple colored test image"""
    img = Image.new('RGB', size, color=color)
    buffer = BytesIO()
    img.save(buffer, format='PNG')
    return base64.b64encode(buffer.getvalue()).decode('utf-8')

# Test images
vial_base64 = create_test_image((0, 255, 0))  # Green
label_base64 = create_test_image((255, 255, 255))  # White

# Test payload
url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-image:generateContent"
api_key = os.getenv('GEMINI_API_KEY')

# Test without imageConfig
payload = {
    "contents": [{
        "parts": [
            {"text": "Replace the label on the vial with the new label design. Keep green background."},
            {"inline_data": {"mime_type": "image/png", "data": vial_base64}},
            {"inline_data": {"mime_type": "image/png", "data": label_base64}}
        ]
    }],
    "generationConfig": {
        "responseModalities": ["IMAGE"],
        "temperature": 0.1,
        "topP": 0.9,
        "topK": 10
    }
}

headers = {"Content-Type": "application/json"}

print(f"Testing Gemini API: {url}")
print(f"API Key: {api_key[:20]}...")
print(f"\nPayload structure:")
print(json.dumps({k: v if k != 'contents' else '...' for k, v in payload.items()}, indent=2))

try:
    response = requests.post(f"{url}?key={api_key}", headers=headers, json=payload, timeout=30)
    print(f"\nStatus Code: {response.status_code}")
    print(f"\nResponse Headers:")
    for k, v in response.headers.items():
        print(f"  {k}: {v}")

    print(f"\nResponse Body:")
    try:
        print(json.dumps(response.json(), indent=2))
    except:
        print(response.text)

    response.raise_for_status()
    print("\n✅ Success!")

except requests.exceptions.HTTPError as e:
    print(f"\n❌ HTTP Error: {e}")
    print(f"\nError Response Body:")
    try:
        print(json.dumps(response.json(), indent=2))
    except:
        print(response.text)
except Exception as e:
    print(f"\n❌ Error: {e}")
