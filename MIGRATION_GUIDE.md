# Migration Guide: google-generativeai → google-genai

**Data migracji:** 29 stycznia 2026
**Dotyczy:** Mockup generation endpoints

---

## Dlaczego migracja?

1. **Deprecated package**: `google-generativeai==0.8.6` używał starego REST API
2. **400 Errors**: Gemini API zwracał błędy 400 Bad Request
3. **Oficjalna dokumentacja**: Google Gemini API 2026 rekomenduje `google-genai`
4. **Lepsze API**: Nowy SDK jest czystszy, prostszy, i lepiej obsługuje obrazy

---

## Zmiany w package

### requirements.txt

```diff
- google-generativeai>=0.8.6
+ google-genai>=1.47.0
```

### Instalacja

```bash
# Aktywuj virtual environment
source .venv/bin/activate

# Usuń stary package
pip uninstall google-generativeai

# Zainstaluj nowy package
pip install google-genai>=1.47.0
```

---

## Zmiany w kodzie

### Import

```diff
- import google.generativeai as genai
+ from google import genai
+ from google.genai import types
```

### Inicjalizacja

```diff
- genai.configure(api_key=config.GEMINI_API_KEY)
- model = genai.GenerativeModel('gemini-2.5-flash-image')
+ client = genai.Client(api_key=config.GEMINI_API_KEY)
```

### Generowanie obrazów

**STARY KOD (REST API):**
```python
import requests
import base64

# Manual base64 encoding
vial_base64 = base64.b64encode(vial_bytes).decode('utf-8')
label_base64 = base64.b64encode(label_bytes).decode('utf-8')

# REST API call
url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-image:generateContent?key={key}"
payload = {
    "contents": [{
        "parts": [
            {"text": prompt},
            {"inline_data": {"mime_type": "image/png", "data": vial_base64}},
            {"inline_data": {"mime_type": "image/png", "data": label_base64}}
        ]
    }],
    "generationConfig": {
        "responseModalities": ["IMAGE"],
        "temperature": 0.1
    }
}

response = requests.post(url, headers=headers, json=payload, timeout=60)
data = response.json()

# Manual extraction
image_data = data['candidates'][0]['content']['parts'][0]['inlineData']['data']
image_bytes = base64.b64decode(image_data)
result_image = PIL.Image.open(BytesIO(image_bytes))
```

**NOWY KOD (SDK):**
```python
from google import genai
from google.genai import types

# No base64 needed - pass PIL.Image directly!
client = genai.Client(api_key=config.GEMINI_API_KEY)

generation_config = types.GenerateContentConfig(
    temperature=0.1,
    top_p=0.85,
    top_k=10,
    response_modalities=["IMAGE"],
)

response = client.models.generate_content(
    model='gemini-2.5-flash-image',
    contents=[prompt, vial_image, label_image],  # PIL Images directly!
    config=generation_config
)

# Simple extraction
for part in response.parts:
    if part.inline_data is not None and part.inline_data.data is not None:
        image_bytes = part.inline_data.data
        result_image = PIL.Image.open(BytesIO(image_bytes))
        break
```

---

## Kluczowe różnice

### 1. Brak ręcznej konwersji base64

**STARY:**
```python
buffered = BytesIO()
image.save(buffered, format="PNG")
base64_str = base64.b64encode(buffered.getvalue()).decode('utf-8')
```

**NOWY:**
```python
# Przekaż PIL.Image bezpośrednio
contents=[prompt, vial_image, label_image]
```

### 2. Ekstrakcja obrazu

**STARY:**
```python
# Manual JSON parsing
image_data = response_data['candidates'][0]['content']['parts'][0]['inlineData']['data']
image_bytes = base64.b64decode(image_data)
```

**NOWY:**
```python
# Bezpośredni dostęp do bytes
for part in response.parts:
    if part.inline_data is not None:
        image_bytes = part.inline_data.data
```

### 3. Konfiguracja

**STARY:**
```python
payload = {
    "generationConfig": {
        "responseModalities": ["IMAGE"],
        "temperature": 0.1,
        "topP": 0.85
    }
}
```

**NOWY:**
```python
config = types.GenerateContentConfig(
    response_modalities=["IMAGE"],
    temperature=0.1,
    top_p=0.85,
    top_k=10
)
```

---

## Zaktualizowane funkcje

### app.py

1. **`_generate_mockup_for_product_with_retry()`** (linie 2643-2744)
   - Nowy SDK
   - Retry logic
   - Retry hints

2. **`_generate_mockup_for_product()`** (linie 2747-2909)
   - Nowy SDK
   - Brak retry (legacy)

### Zaktualizowane endpointy

1. **`/api/generate-single-mockup`** (linie 2090-2240)
2. **`/api/generate-mockups-from-labels`** (linie 3209-3506)
3. **`/api/generate-mockup`** (linie 2266-2390) - **ZAKTUALIZOWANY 29.01**
4. **`/api/generate-batch-mockups`** (linie 3534-3584) - **ZAKTUALIZOWANY 29.01**

---

## Korzyści migracji

✅ **Brak manual base64 encoding** - SDK obsługuje konwersję
✅ **Czystszy kod** - 67% mniej linii w `/api/generate-mockup`
✅ **Lepsze error handling** - Structured exceptions
✅ **PIL.Image support** - Direct image passing
✅ **Zgodność** - Oficjalna dokumentacja Google 2026
✅ **Reliability** - Brak 400 errors

---

## Testowanie po migracji

1. **Restart serwera:**
   ```bash
   ./restart.sh
   ```

2. **Test single mockup:**
   - Web UI → Mockup Generator → Generate Single Mockup
   - Upload vial + label
   - Check result

3. **Test batch mockups:**
   - Web UI → Combined Generator → Step 2
   - Select generated labels
   - Generate mockups
   - Download ZIP

4. **Check logs:**
   ```bash
   tail -f logs/app.log | grep "Gemini"
   ```

---

## Troubleshooting

### Error: "No module named 'google.genai'"

```bash
source .venv/bin/activate
pip install google-genai>=1.47.0
```

### Error: "'Image' object has no attribute 'mode'"

Używasz starego kodu. Sprawdź czy używasz:
```python
# ✅ POPRAWNIE
image_bytes = part.inline_data.data

# ❌ BŁĄD (stary kod)
image = part.as_image()
```

### Error: 400 Bad Request

Sprawdź czy używasz nowego SDK:
```python
# ✅ POPRAWNIE
from google import genai
client = genai.Client(api_key=...)

# ❌ BŁĄD (stary kod)
import google.generativeai as genai
genai.configure(api_key=...)
```

---

## Rollback (gdyby było potrzebne)

Jeśli z jakiegoś powodu potrzebujesz wrócić do starego SDK:

```bash
pip uninstall google-genai
pip install google-generativeai==0.8.6
```

Przywróć stary kod z git:
```bash
git log --oneline  # Find commit before migration
git checkout <commit-hash> app.py
```

**⚠️ NIE ZALECANE** - stary SDK jest deprecated

---

## Więcej informacji

- **Gemini API Docs**: https://ai.google.dev/gemini-api/docs/image-generation
- **google-genai PyPI**: https://pypi.org/project/google-genai/
- **Internal docs**: `backup_settings/MOCKUP_GENERATION.md`
- **Changelog**: `CHANGELOG.md`
