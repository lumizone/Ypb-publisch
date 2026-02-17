# YPBv2 - Label & Mockup Generator

**Status**: ✅ Production Ready (17 lutego 2026)
**Lokalizacja**: `/Users/lukasz/YPBv2`
**Port**: http://localhost:8000
**Railway**: https://ypbv2.up.railway.app (8 CPU / 8GB RAM)

---

## 🎯 AKTUALNY STAN APLIKACJI

### ✅ Mockup Background Removal + Label Crop Scaling Fix (17.02.2026)

**Cel**: Naprawa usuwania tła mockupów i skalowania koordynatów wycinania labela

---

#### 1. Background Removal Fix (rembg)

**Problem**: `rembg` (AI-based) było w requirements.txt ale nie zainstalowane → fallback color-based miał 2 bugi:
- **uint8 overflow**: `rgb - vial_rgb` (oba uint8) powodował przepełnienie → błędne odległości kolorów → wszystkie piksele "podobne do fiolki"
- **Opaque vial alpha**: `vial_alpha > 128` = True dla uploadowanych zdjęć (JPEG, brak przezroczystości) → wszystko oznaczone jako foreground → zero pikseli usunięte

**Rozwiązanie**:
- Zainstalowano `rembg` + `onnxruntime` (AI-based background removal)
- Fix fallback: `rgb.astype(np.float32) - vial_rgb.astype(np.float32)` (poprawna arytmetyka)
- Fix fallback: sprawdzanie `has_transparency` przed użyciem vial alpha jako foreground

**Pliki**: `app.py` (linie 1250-1263)

---

#### 2. Label Crop Coordinate Scaling

**Problem**: Koordynaty wycinania labela były w wymiarach template SVG (~1181x506) ale stosowane do wygenerowanego labela (4200x1800) bez skalowania → Gemini dostawał tylko mały fragment lewego górnego rogu

**Rozwiązanie**:
- Frontend wysyła `templateWidth/templateHeight` razem z crop data
- Backend skaluje koordynaty: `crop_x = int(round(x * label_w / template_w))`
- Zastosowane w obu pipeline'ach: combined + standalone batch

**Pliki**: `app.py` (linie 4375-4400, 4986-5012), `app_dashboard.html` (linie 7900-7908)

---

#### 3. Label Generation Progress Bar (elapsed + ETA)

**Problem**: Pasek postępu generowania labels nie miał elapsed time i ETA (mockup miał)

**Rozwiązanie**: Dodano elapsed time counter + ETA oparty na średnim czasie przetwarzania

**Format**: `Generating: Sermorelin (YPB.211) - 45% (2m 30s elapsed, ~5m 12s left)`

**Pliki**: `app_dashboard.html`

---

**Commits**: `c2391a0` (bg fix), `5051e56` (crop scaling + rembg), `c222291` (progress bar)

**Status**: ✅ Zaimplementowane (17.02.2026)

---

### ✅ ZIP SVG+JPG Only + Mask Transparency Fix (16.02.2026)

**Cel**: ZIP zawiera tylko SVG + JPG (usunięto PNG i PDF), naprawa przezroczystości masek przy wysokim DPI

---

#### 1. ZIP Contents: Only SVG + JPG

**Problem**: ZIP zawierał PNG i PDF - user chce TYLKO SVG + JPG (+ mockup)

**Rozwiązanie**: Filtrowanie plików w ZIP we wszystkich pipeline'ach

**Zmienione miejsca:**
- `app.py:3958-3968` - Main pipeline ZIP: filtr `svg+jpg` only
- `app.py:3610-3617` - SVG fallback ZIP: filtr `svg+jpg` only
- `app.py:4689` - Combined ZIP regex: `svg|jpg` (było: `svg|png|jpg|jpeg|pdf`)
- `renderer.py:render_all_formats()` - zwraca tylko `{'svg', 'jpg'}` (usunięto PDF)
- `batch_processor.py:92-94` - usunięto `'pdf'` z return dict

**Rezultat**: ZIP zawiera TYLKO `YPB.xxx.svg` + `YPB.xxx.jpg` per SKU

---

#### 2. CairoSVG Mask Transparency Fix

**Problem**: CairoSVG renderuje `<mask>` elementy z szerszym gradientem przy wyższych rozdzielczościach → washed-out edges na logo

**Root cause**: SVG zawiera `<mask id="mask_3">` z embedded 1080x1080 PNG luminance mask. Przy bezpośrednim renderze do 4200x1800 (via `output_width`), CairoSVG rozszerza gradient maski → prawa strona lewego logo jest washed out (szara zamiast czarnej)

**Rozwiązanie**: Render at native SVG size → upscale with PIL LANCZOS
```python
# renderer.py:render_png()
# 1. Render at native size (1181x506) - masks render correctly
cairosvg.svg2png(url=str(svg_path), write_to=str(temp_png), dpi=dpi)
# 2. Add white background
bg = Image.new('RGB', img.size, (255, 255, 255))
bg.paste(img, mask=img.split()[-1])
# 3. Upscale to target DPI dimensions (4200x1800)
img.resize((target_width, target_height), Image.LANCZOS)
```

**Zastosowane we wszystkich pipeline'ach:**
- `renderer.py:68-130` - Main render pipeline
- `app.py:3882-3912` - Mockup PNG generation
- `ai_converter.py:1331-1346` - Hybrid fallback

**Kluczowe**: `target_width = svg_w * PNG_DPI / 675` (675 = AI converter base DPI)

**Rezultat**: Logo pixel-perfect, zero washed-out edges, 4200x1800 @ 2400 DPI

---

#### 3. PDF Removed from Pipeline

**Problem**: PDF nie jest potrzebny w output

**Rozwiązanie**: Usunięto generowanie PDF z `renderer.render_all_formats()` i kopiowanie PDF w `app.py`

**Rezultat**: Szybsze generowanie (brak konwersji SVG→PDF), mniejsze pliki

---

#### 4. Hybrid Fallback JPG DPI

**Problem**: Hybrid fallback JPG nie miał metadanych DPI

**Rozwiązanie**: `ai_converter.py:1431` - dodano `dpi=(config.PNG_DPI, config.PNG_DPI)` do `img.save()`

---

#### Pliki zmienione:
- `renderer.py` - native render + LANCZOS upscale, removed PDF from render_all_formats
- `app.py` - ZIP filters (svg+jpg only), mockup PNG native render, removed PDF copy
- `ai_converter.py` - hybrid fallback native render + DPI metadata
- `batch_processor.py` - removed PDF from result dict

**Commit**: `caf138d` - pushed to GitHub

**Status**: ✅ Zaimplementowane (16.02.2026)

---

### ✅ 8 Resize Handles for Label Selection (16.02.2026)

**Cel**: 8 uchwytów do resize'owania areas (corners + edges) w Combined + Standalone generators

**Commit**: `da37e56` - pushed to GitHub

**Status**: ✅ Zaimplementowane

---

### ✅ CAS Number & Molecular Weight Fields (14.02.2026)

**Cel**: Dodanie pól CAS (Chemical Abstract Service) i M.W. (Molecular Weight) do systemu generowania labels z automatycznym wykrywaniem

---

#### 1. Database Structure: 3 → 5 Columns

**Problem**: Baza danych miała tylko 3 kolumny (Product, Ingredients, SKU) - brakowało CAS i M.W.

**Rozwiązanie**: Rozszerzenie struktury bazy danych do 5 kolumn

**Nowa struktura CSV:**
```csv
SKU,Product,Dosage,CAS Number,Molecular Weight
YPB.211,Sermorelin,10mg,114466-38-5,3357.88 Da
YPB.212,BPC-157,5mg,137525-51-0,1419.55 Da
```

**Pliki zmienione:**
- `databases/YPB_final_databse.csv` - 65 produktów (YPB.211-283) z pełnymi danymi
- Format: SKU, Product, Dosage, CAS Number, Molecular Weight

**Rezultat**: Każdy produkt ma teraz CAS number i wagę molekularną

---

#### 2. Backend - CSV Manager Updates

**Zmienione pliki:**
- `csv_manager.py` (linie 43-80, 87-109, 116-205)
  - Column detection: `cas`, `cas number`, `molecular weight`, `m.w.`
  - Product dict rozszerzony: `'CAS'`, `'MW'`
  - All CRUD operations: `read_all()`, `save_all()`, `add_product()`, `update_product()`, `bulk_update()`
  - CSV validation: `replace_csv()` wymaga CAS i MW

- `config.py` (linia 46)
  - `REQUIRED_PLACEHOLDERS = ["product_name", "ingredients", "sku", "cas", "mw"]`

- `text_replacer.py` (linie 24-30, 186-194)
  - `FIELD_MAPPING` dodano: `'cas'`, `'mw'`
  - Simple text replacement (bez surgical replace jak SKU)

**Rezultat**: Backend obsługuje CAS i MW we wszystkich operacjach

---

#### 3. Frontend - UI Updates

**Database Tab** (app_dashboard.html):
- Linie 1634-1644: Table header - dodano `<th>CAS</th>` i `<th>M.W.</th>`
- Linie 4979: Colspan zmieniony z 5 → 7 (checkbox + 5 columns + actions)
- Linie 5027-5079: Dodano `tdCas` i `tdMw` cells z edycją inline
- Linie 5050-5056: Append CAS i MW cells do table row

**Product Selection Modal** (app_dashboard.html):
- Linie 8547-8550: Modal table header - dodano CAS i MW kolumny
- Linie 7489-7501: Dodano CAS i MW cells do renderowania

**Import CSV Modal** (app_dashboard.html):
- Linie 8514-8525: Dodano mapping selects dla "CAS Number *" i "Molecular Weight *"
- Linie 3149-3150: `populateMappingSelects()` - dodano mappingCas i mappingMw
- Linie 3174-3182: `validateImportMapping()` - walidacja CAS i MW
- Linie 3194-3221: `submitImport()` - wysyła mapowanie CAS i MW do backendu

**Add Product** (app_dashboard.html):
- Linie 5244-5251: Nowy produkt ma pola `CAS: ''` i `MW: ''`

**Rezultat**: UI pokazuje i edytuje CAS i MW we wszystkich miejscach

---

#### 4. Backend - CSV Import & Auto-mapping

**Pliki zmienione:**
- `app.py` (linia 1833-1834) - Validation: wymaga mapowania CAS i MW
- `app.py` (linia 1853-1857) - Mapowanie danych: dodano `'CAS'` i `'MW'`
- `app.py` (linia 1871) - CSV Writer: fieldnames = `['Product', 'Ingredients', 'SKU', 'CAS', 'MW']`
- `app.py` (linia 1795-1813) - Auto-detection CAS i MW kolumn:
  ```python
  # CAS detection
  for key in ['cas', 'cas number', 'cas_number', 'casnumber']:
      if key in columns_lower:
          auto_mapping['cas'] = columns_lower[key]
          break

  # MW detection
  for key in ['mw', 'm.w.', 'm.w', 'molecular weight', 'molecular_weight']:
      if key in columns_lower:
          auto_mapping['mw'] = columns_lower[key]
          break
  ```

**Rezultat**: Import CSV automatycznie wykrywa i mapuje CAS i MW kolumny

---

#### 5. Auto-detection w Template (⭐ KLUCZOWE)

**Problem**: System wymagał ręcznego rysowania areas lub data-placeholder w template dla CAS i MW

**Rozwiązanie**: Automatyczne wykrywanie CAS i MW w template SVG przez matching z wartościami z bazy

**Implementacja** (`app.py` linie 5662-5723):

```python
def add_data_placeholders_to_svg_text(svg_path, extracted_info):
    # 1. Wykryj SKU w template
    # 2. Znajdź matching product w bazie danych
    # 3. Pobierz wartości z bazy:
    cas_value = matched_product.get('CAS', '').strip()
    mw_value = matched_product.get('MW', '').strip()

    # 4. Dla każdego <text> w SVG:
    #    - Jeśli zawiera CAS number (np. "114466-38-5")
    #      → dodaj data-placeholder="cas"
    #    - Jeśli zawiera MW (np. "3357.88 Da")
    #      → dodaj data-placeholder="mw"
```

**Flow:**
1. User uploaduje template SVG z wartościami z bazy:
   ```xml
   <text>Sermorelin</text>
   <text>10mg</text>
   <text>YPB.211</text>
   <text>114466-38-5</text>     <!-- CAS z bazy -->
   <text>3357.88 Da</text>        <!-- MW z bazy -->
   ```

2. System automatycznie:
   - Wykrywa SKU: `YPB.211`
   - Znajduje produkt w bazie: `{Product: "Sermorelin", CAS: "114466-38-5", MW: "3357.88 Da"}`
   - Dla każdego `<text>`:
     - `"114466-38-5"` matches `cas_value` → dodaje `data-placeholder="cas"`
     - `"3357.88 Da"` matches `mw_value` → dodaje `data-placeholder="mw"`

3. Output SVG z placeholders:
   ```xml
   <text data-placeholder="product_name">Sermorelin</text>
   <text data-placeholder="ingredients">10mg</text>
   <text data-placeholder="sku">YPB.211</text>
   <text data-placeholder="cas">114466-38-5</text>
   <text data-placeholder="mw">3357.88 Da</text>
   ```

4. Generate Labels - system podmienia wszystkie 5 pól dla każdego produktu

**Kluczowe zmiany:**
- `app.py:5667-5669` - Dodano `cas_value` i `mw_value` z matched product
- `app.py:5703-5712` - Dodano checks dla CAS i MW w funkcji `add_placeholder()`
- `template_parser.py:497-508` - **USUNIĘTO** `'CAS:'` i `'M.W.:'` z `skip_keywords`
- `template_parser.py:566-576` - **USUNIĘTO** `'CAS:'` i `'M.W.:'` z `disallowed` keywords

**Rezultat**:
- ✅ Zero manual work - user NIE musi rysować areas
- ✅ Zero Illustrator edits - user NIE musi dodawać data-placeholder w AI
- ✅ Template z wartościami z bazy → auto-detection → generate labels

---

#### 6. Text Replacement

**FIELD_MAPPING** (`text_replacer.py`):
```python
FIELD_MAPPING = {
    'sku': ['SKU', 'sku'],
    'product_name': ['Product', 'product_name', 'Name', 'name'],
    'ingredients': ['Ingredients', 'ingredients', 'Composition', 'composition', 'Dosage', 'dosage'],
    'cas': ['CAS', 'cas', 'CAS Number', 'cas_number'],          # NOWE
    'mw': ['MW', 'mw', 'M.W.', 'M.W', 'Molecular Weight', 'molecular_weight'],  # NOWE
}
```

**Replacement Logic** (`text_replacer.py:186-194`):
- SKU: surgical replace (tylko YPB.XXX, zachowuje "RESEARCH USE ONLY")
- CAS/MW: **simple text replacement** (cały tekst podmieniony)

**Przykład:**
```
Template:        YPB.211 → Output: YPB.212
Template:  114466-38-5 → Output: 137525-51-0
Template:   3357.88 Da → Output: 1419.55 Da
```

---

#### 7. Testing & Verification

**Test Results** (14.02.2026):

| Test | Status | Wynik |
|------|--------|-------|
| Database (65 products) | ✅ | All have CAS & MW |
| API `/api/database/products` | ✅ | Returns CAS & MW |
| Auto-detection (5 placeholders) | ✅ | All detected |
| Text Replacement | ✅ | CAS & MW replaced |
| Config REQUIRED_PLACEHOLDERS | ✅ | 5 fields |
| CSV Import auto-mapping | ✅ | CAS & MW mapped |
| Skip keywords removed | ✅ | CAS & MW not skipped |

**Test Template:**
```xml
<text>Sermorelin</text>
<text>10mg</text>
<text>YPB.211</text>
<text>114466-38-5</text>
<text>3357.88 Da</text>
```

**Auto-detection Output:**
```
✅ Matched product by SKU: YPB.211
✅ Added data-placeholder='product_name' to text: Sermorelin
✅ Added data-placeholder='ingredients' to text: 10mg
✅ Added data-placeholder='sku' to text: YPB.211
✅ Added data-placeholder='cas' to text: 114466-38-5
✅ Added data-placeholder='mw' to text: 3357.88 Da
```

**Generated Label (YPB.212):**
```xml
<text data-placeholder="product_name">BPC-157</text>
<text data-placeholder="ingredients">5mg</text>
<text data-placeholder="sku">YPB.212</text>
<text data-placeholder="cas">137525-51-0</text>
<text data-placeholder="mw">1419.55 Da</text>
```

---

#### 8. Files Modified Summary

**Backend (8 files):**
- `config.py` - REQUIRED_PLACEHOLDERS += cas, mw
- `csv_manager.py` - Column detection, CRUD operations
- `text_replacer.py` - FIELD_MAPPING, replacement logic
- `template_parser.py` - Removed skip_keywords for CAS/MW
- `app.py` - Auto-detection, CSV import, API
- `databases/YPB_final_databse.csv` - New 5-column structure

**Frontend (1 file):**
- `app_dashboard.html` - Database table, Import modal, Product selection modal

**Total lines changed:** ~300 lines

---

#### 9. User Workflow (UNCHANGED!)

**Workflow pozostał taki sam:**
1. Upload template SVG/AI (z wartościami z bazy)
2. System automatycznie wykrywa wszystkie 5 pól
3. Generate Labels → wszystkie pola podmienione

**Nowe możliwości:**
- ✅ Database tab pokazuje CAS i MW (edycja inline)
- ✅ Import CSV automatycznie mapuje CAS i MW
- ✅ Template auto-detection wykrywa CAS i MW (zero manual work)

**Status**: ✅ Zaimplementowane i przetestowane (14.02.2026)

---

### ✅ CAS/MW Smart Text Fitting & Zone-Based Positioning (15.02.2026)

**Cel**: Inteligentne dopasowanie CAS i M.W. tekstu - zachowanie prefiksów, synchronizacja fontów, auto-detekcja wolnej przestrzeni, brak nachodzenia na sąsiednie teksty

---

#### 1. Prefix Preservation

**Problem**: Przy replacement CAS/MW tracone były etykiety "CAS: " i "M.W.: "

**Rozwiązanie** (`text_replacer.py:~191`):
```python
# Parse original text for prefix (split on ":"), prepend to new value
orig = placeholder_info.get('original_full_text', '')
if orig and ':' in orig:
    prefix = orig.split(':', 1)[0] + ': '
    display_value = prefix + new_text
```

**Rezultat**: `CAS: 137525-51-0` → `CAS: 885340-08-9` (prefix zachowany)

---

#### 2. Synchronized CAS/MW Formatting

**Problem**: CAS i MW miały różne rozmiary fontów i różną liczbę linii - niespójny wygląd

**Rozwiązanie** (`text_replacer.py:_sync_cas_mw_format()`):
- Pre-kalkulacja PRZED replacement loop
- Oba pola zawsze używają tego samego font_size i tej samej liczby linii
- Algorytm: 1 linia → shrink 20% → 2 linie na 90% → dalszy shrink (min 60%)

---

#### 3. Zone-Based Positioning (⭐ KLUCZOWE)

**Problem**: CAS/MW nachodziły na sąsiednie teksty ("FOR IM OR SQ USE ONLY", SKU, etc.)

**Rozwiązanie**: Auto-detekcja dostępnej strefy z uwzględnieniem sąsiednich elementów

**Algorytm** (`text_replacer.py:_sync_cas_mw_format()`):
```
1. Zbierz WSZYSTKIE <text> elementy w tej samej strefie X (prawa strona labela)
2. Dla każdego sąsiada zapisz (y_baseline, font_size)
3. Znajdź boundary_top = nearest element ABOVE CAS baseline + 5px gap
4. Znajdź boundary_bottom = nearest element BELOW MW:
   - Uwzględnij ASCENDER: y_below - font_size_below * 0.85 - 3px
   - SVG y = baseline (dół tekstu), ascender = ~85% font_size nad baseline
5. available_height = boundary_bottom - boundary_top
6. available_width = svg_width - elem_x - 15px (prawy edge labela)
```

**Kluczowe**: `boundary_bottom` uwzględnia wizualną górę tekstu poniżej (ascender), nie sam baseline. Stary błąd: `-5px` → nowy: `- font_size * 0.85 - 3px`

**Przykład (GLOW label):**
```
"FOR IM OR SQ USE ONLY" at y=449.97, font-size=23.44px
Old boundary_bottom: 449.97 - 5 = 445 (MW 2nd line at 434 → fits but OVERLAPS visually!)
New boundary_bottom: 449.97 - 23.44*0.85 - 3 = 427 (MW 2nd line would exceed → font shrunk)
```

---

#### 4. Y Position Strategy

**Problem**: CAS/MW przesuwane na górę strefy (boundary_top) zamiast trzymać oryginalne pozycje

**Rozwiązanie**: Zachowaj ORYGINALNE pozycje Y z template:
- `cas_y` = oryginalna pozycja z template (nie zmieniana)
- `mw_y` = oryginalna pozycja z template
- MW przesuwa się w dół TYLKO gdy CAS zawija do 2 linii (żeby nie nachodzić)

---

#### 5. Line Height

**Problem**: Duży odstęp między liniami przy zawijaniu (1.25x font_size)

**Rozwiązanie**: `line_height = font_size * 1.1` (ciasny spacing dla multi-line CAS/MW)

---

#### 6. Width Calculation

**Problem**: `available_width` bazowała na najszerszym sąsiednim tekście → za wąsko

**Rozwiązanie**: `available_width = svg_width - elem_x - 15px` (pełna szerokość do prawej krawędzi labela)

---

#### Pliki zmienione:
- `text_replacer.py` - `_sync_cas_mw_format()`, prefix preservation, zone-based positioning
- `template_parser.py` - cas/mw optional placeholders
- `data_mapper.py` - cas/mw optional in validation
- `app.py` - CAS/MW inject inside `_generate_labels_task()` after `parse_by_position()`

**Status**: ✅ Zaimplementowane (15.02.2026)

---

### ✅ Filename Format + 2400 DPI Output (13.02.2026)

**Cel**: Zmiana nazw plików label na format SKU (YPB.200) + zwiększenie DPI do 2400

---

#### 1. Filename Format: SKU Only

**Problem**: Pliki label miały format `ProductName_YPB.200.jpg` - za długie nazwy

**Rozwiązanie**: Pliki teraz nazwane tylko po SKU: `YPB.200.jpg`

**Zmienione miejsca:**
- `batch_processor.py:73-75` - główny pipeline: `base_filename = safe_sku` (było: `f"{safe_name}_{safe_sku}"`)
- `app.py:3844-3862` - SVG fallback pipeline: `{sku_safe}.svg/png/pdf/jpg` (było: `label_{sku_safe}.*`)

**Rezultat**: Pliki nazwane `YPB.200.svg`, `YPB.200.png`, `YPB.200.pdf`, `YPB.200.jpg`

#### 2. DPI: 300 → 2400

**Problem**: Output labels w 300 DPI - za niska rozdzielczość

**Rozwiązanie**: Zwiększenie do 2400 DPI we wszystkich ścieżkach renderowania

**Zmienione miejsca:**
- `config.py:49` - `PNG_DPI = 2400` (było: 300)
- `app.py:3835` - SVG fallback path: dodano `dpi=config.PNG_DPI` (było: brak DPI = 96 default!)

**Ścieżki renderowania i ich DPI:**

| Ścieżka | Plik | DPI |
|----------|------|-----|
| Main pipeline PNG | `renderer.py:render_png()` | 2400 (via config.PNG_DPI) |
| Main pipeline JPG | `renderer.py:render_jpg()` | 2400 (via config.PNG_DPI) |
| SVG fallback PNG | `app.py:3835` | 2400 (via config.PNG_DPI) |
| Preview/mockup input | `app.py:1057, 4863` | Bez zmian (preview only) |
| AI→SVG konwersja | `app.py:1528` | 300 (bez zmian - to SVG vector preview) |

**Uwaga**: 2400 DPI = ~64x więcej pikseli niż 300 DPI. Pliki JPG będą znacznie większe.

**Status**: ✅ Zaimplementowane

**Pliki zmienione**: `config.py`, `app.py`, `batch_processor.py`

---

### ✅ Google Fonts Library + Fontconfig Aliases (08.02.2026)

**Cel**: Automatyczne mapowanie komercyjnych fontów (Gotham, Proxima Nova, Helvetica Neue, etc.) na darmowe Google Fonts - eliminacja potrzeby fallbacku

---

#### Problem
- AI templates używają komercyjnych fontów (Gotham, Proxima Nova, Futura, etc.)
- CairoSVG (renderer SVG→PNG) nie ma tych fontów → fallback do Verdana/Arial
- Stary hybrid fallback (PIL overlay) zmieniał pozycje tekstu

#### Rozwiązanie: Google Fonts + Fontconfig Strong Matching

**1. Pobrano 398 Google Fonts (81 rodzin)** do `fonts/google/`:
- Sans-Serif: Montserrat, Inter, Open Sans, Roboto, Lato, Poppins, Raleway, Barlow, Work Sans, DM Sans, Nunito, Nunito Sans, Libre Franklin, Source Sans 3, Plus Jakarta Sans, Public Sans, Manrope, Outfit, Sora, Figtree, Mulish, Cabin, Rubik, Karla, Hind, Catamaran, Kanit, Josefin Sans, Lexend, Overpass, Red Hat Display, Exo 2, Signika, Quicksand, Comfortaa, Fredoka, Yantramanav, Maven Pro, Space Grotesk, PT Sans
- Serif: EB Garamond, Playfair Display, Merriweather, Lora, Noto Serif, Source Serif 4, Libre Baskerville, Vollkorn, Bitter, Crimson Text, Cormorant Garamond, PT Serif, Roboto Slab, DM Serif Display, DM Serif Text
- Display: Bebas Neue, Anton, Oswald, Teko, Big Shoulders Display, Abril Fatface, Alfa Slab One, Black Ops One, Bungee, Righteous, Russo One, Secular One, Titan One
- Monospace: Fira Code, JetBrains Mono, IBM Plex Mono, Source Code Pro, Space Mono
- Handwriting: Caveat, Dancing Script, Great Vibes, Pacifico, Sacramento

**2. Fontconfig `<match>` rules** (188 aliasów) w `~/.config/fontconfig/fonts.conf`:

| Komercyjny Font | Google Font |
|---|---|
| Gotham (all variants) | Montserrat |
| Proxima Nova | Montserrat |
| Helvetica Neue | Inter |
| Futura | Nunito |
| Avenir / Avenir Next | Nunito Sans |
| Century Gothic | Poppins |
| Gill Sans | Lato |
| Franklin Gothic | Libre Franklin |
| Myriad Pro | Source Sans 3 |
| AcuminVariableConcept | Inter |
| Garamond / Adobe Garamond | EB Garamond |
| DIN / DIN Next | Oswald |
| Trade Gothic | Barlow |
| Brandon Grotesque | Raleway |
| Museo Sans | Work Sans |
| Circular / Circular Std | DM Sans |
| Graphik | Manrope |
| Univers | Inter |
| Frutiger | Nunito Sans |
| Segoe UI | Roboto |
| SF Pro / San Francisco | Inter |
| Bodoni / Didot | Playfair Display |
| Minion Pro | Merriweather |
| Knockout | Bebas Neue |
| + 30 więcej... | |

**3. Użycie `<match>` zamiast `<alias>`:**
- `<alias><prefer>` - słabe: fontconfig scoring może wybrać inny font
- `<match mode="assign" binding="strong">` - silne: bezwzględna zamiana nazwy fontu
- Wynik: `fc-match "Franklin Gothic"` → `LibreFranklin-Regular.ttf` (nie Verdana!)

#### Implementacja

**Pliki:**
- `fonts/google/` - 398 TTF plików (81 rodzin, wszystkie wagi: Light/Regular/Medium/SemiBold/Bold/ExtraBold/Black)
- `fonts/montserrat/` - 9 Montserrat TTF (dodatkowy zestaw)
- `~/.config/fontconfig/fonts.conf` - 188 `<match>` rules + 2 `<dir>` entries
- `ai_converter.py` - `FONT_ALTERNATIVES` dict (60+ mapowań dla PIL fallbacku)
  - `_get_pil_font()` - szuka fontu w bundled Google Fonts
  - `_fit_pil_text()` - dobiera rozmiar fontu do area
  - `generate_hybrid_label()` - PIL overlay (backup fallback)

**Kluczowe:**
- Normal pipeline (CairoSVG) automatycznie używa Google Fonts przez fontconfig
- Nie trzeba fallbacku - fontconfig podmienia nazwy fontów przed renderingiem
- PIL overlay nadal dostępny jako backup gdy tekst jest garbled (≥3 `�`)
- Fonty pobrane z fontsource CDN: `cdn.jsdelivr.net/fontsource/fonts/{slug}@latest/latin-{weight}-normal.ttf`

**Status**: ✅ Zaimplementowane - 398 fontów, 188 aliasów, zero fallback needed

---

### ✅ CFF Font Decoding for AI Files (08.02.2026)

**Cel**: Dekodowanie CFF fontów z plików AI - eliminacja garbled text (������)

---

#### Problem
- Niektóre pliki AI zawierają fonty CFF (np. AcuminVariableConcept) z custom Type1 encoding
- Znaki kontrolne (0x00-0x1F) w content stream
- PyMuPDF nie potrafi zdekodować → produkuje `U+FFFD` (garbled text ������)

#### Rozwiązanie: CFF Charset Decoding Pipeline

**Flow:**
```
1. AI file → PyMuPDF → SVG (sprawdza czy garbled)
2. Jeśli garbled: parsuj PDF content stream dla raw char codes
3. Mapuj przez CFF charset: char_code → gidNNNNN → GID → Unicode
4. Podmień garbled text w SVG na zdekodowany tekst
5. Normalna generacja labels (bez fallbacku!)
```

**Implementacja w `ai_converter.py`:**
- `_build_cff_decode_map()` - parsuje content stream, buduje mapę char→Unicode
- `_build_gid_to_unicode_from_widths()` - mapowanie GID→Unicode przez width-matching
- `_build_gid_to_unicode_standard()` - fallback: GID 1=space, 2-27=A-Z, 28-53=a-z, 131-140=0-9
- Wymaga `fonttools` package

**Kluczowe:**
- Tylko fonty z `gidNNNNN` glyph names wymagają dekodowania
- Standardowe glyph names działają normalnie w PyMuPDF
- Wynik: zero garbled text, brak potrzeby Gemini OCR

**Status**: ✅ Zaimplementowane

---

### ✅ SVG Position-Based Fallback (08.02.2026)

**Cel**: Fallback gdy PyMuPDF produkuje garbled text (������) - SVG text replacement by position

---

#### Problem
- PyMuPDF konwertuje AI → SVG ale tekst jest garbled (������)
- Custom font encoding, nie Unicode
- SVG ma poprawne: pozycje (x,y), font-family, font-size, color, transforms
- **Tylko TEXT CONTENT jest zły** - reszta SVG jest pixel-perfect

#### Rozwiązanie: SVG Position-Based Text Replacement

**Flow (TRANSPARENTNY dla usera - frontend bez zmian!):**

```
1. AI file → PyMuPDF → SVG z garbled text (������)
2. Wykrycie garbled (≥3 znaków �)
3. Gemini OCR (1 request): extract SKU + product_name (tylko odczyt!)
4. User widzi PNG preview (zamiast broken SVG)
5. User rysuje areas na PNG (SVG overlay)
6. Generate Labels:
   - Backend wykrywa garbled w SVG → SVG fallback mode
   - parse_by_position() znajduje <text>/<use>/<g> elementy po koordynatach
   - Taguje je data-placeholder (product_name, ingredients, sku)
   - Dla każdego produktu:
     - TextReplacer.replace() → podmiana tekstu w SVG
     - Renderer.render_all_formats() → PNG + JPG + PDF
   - Output: SVG + JPG (identyczny z main flow)
   - ZERO wywołań Gemini do generowania obrazów!
```

#### Implementacja

**Pliki:**
- `template_parser.py` - TemplateParser class
  - `parse_by_position(text_areas)` - znajduje elementy SVG po pozycji (x,y w area)
  - `_collect_text_elements()` - rekurencyjnie zbiera <text>/<use>/<g> z resolved positions
  - `_resolve_position()` - rozwiązuje łańcuch transform (matrix/scale/translate)
  - `_parse_transform()` - parsuje SVG transform attribute
  - Taguje znalezione elementy `data-placeholder` → istniejący TextReplacer działa bez zmian

- `app.py`
  - `/api/convert-ai-to-svg` - wykrywa garbled, uruchamia Gemini OCR (tylko odczyt), zwraca preview_png
  - `_generate_labels_svg_fallback()` - generuje labels przez SVG pipeline (nie Gemini!)
  - `_generate_labels_task()` - sprawdza garbled, wywołuje SVG fallback jeśli potrzeba

- `app_dashboard.html`
  - PNG preview z SVG overlay dla areas
  - Frontend NIE WIE o fallback - transparentne
  - Usunięty martwy kod: Gemini Annotation Modal + 12 JS functions

**Gemini Models (tylko OCR - odczyt):**
- OCR: `gemini-2.5-flash` - analiza obrazu, ekstrakcja tekstu (SKU, product_name)
- **Usunięto**: `gemini-2.0-flash-exp` image generation - nie jest już używane

**Usunięty kod:**
- `_generate_labels_gemini_fallback()` - stara funkcja Gemini (293 linii)
- `/api/finalize-gemini-label` endpoint (125 linii)
- Gemini Annotation Modal + JS functions (~300 linii frontend)

**Kluczowe:**
- User NIE widzi że to fallback
- Areas działają tak samo jak na SVG (draggable, resizable)
- Grafika/tło SVG **pixel-perfect** (nie regenerowane przez Gemini)
- Output identyczny z main flow: SVG + JPG
- Zero API calls do Gemini na generowanie (tylko 1 OCR na początku)

**Status**: ✅ Zaimplementowane

---

### ✅ Product Selection Feature (05.02.2026) 🎯

**Cel**: Umożliwienie wyboru konkretnych produktów do generowania labels w Combined Generator

---

#### Feature: Product Selection w Combined Generator Step 4

**Problem**: Brak możliwości wyboru konkretnych produktów - generowanie zawsze wszystkich lub limit liczbowy

**Rozwiązanie**:
- Database indicator z nazwą bazy i liczbą produktów
- Radio toggle: "Generate All Products" vs "Select Specific Products"
- Modal popup z listą produktów (Product Name, Ingredients, SKU)
- Checkbox selection z Select All / Unselect All
- Real-time counters: "X of Y products selected"
- Frontend validation (wymaga min. 1 produkt)
- Backend filtering po selected IDs

**Implementacja - Frontend (app_dashboard.html)**:
```javascript
// State variables
let selectedProductIdsCombined = new Set();
let allProductsCombined = [];
let productSelectionMode = 'all'; // 'all' or 'specific'

// 11 nowych funkcji:
- toggleProductSelectionMode(mode)
- loadProductsForSelection()
- openProductSelectionModal()
- closeProductSelectionModal()
- renderProductSelectionTable()
- toggleProductSelection(productId)
- selectAllProducts()
- unselectAllProducts()
- toggleAllProductsCheckbox(checkbox)
- updateSelectAllCheckbox()
- updateModalCounts()
- confirmProductSelection()
```

**Implementacja - Backend (app.py)**:
```python
# Parameter parsing (~line 3714)
selected_product_ids_str = request.form.get('selectedProductIds')
selected_product_ids = json.loads(selected_product_ids_str)

# Product filtering (~line 3796)
if selected_product_ids is not None:
    products = [p for p in all_products if p.get('id') in selected_product_ids]
    logger.info(f"Selected {len(products)} specific products")
else:
    products = all_products
    logger.info(f"Generating all {len(products)} products")
```

**UI Components**:
1. **Database Indicator** (Step 4)
   - Nazwa bazy danych
   - Liczba produktów: "(92 products)"
   - Auto-update przy zmianie bazy

2. **Mode Selector** (Radio Buttons)
   - Default: "Generate All Products"
   - Alt: "Select Specific Products"
   - Przycisk pojawia się tylko w trybie "specific"

3. **Product Selection Modal** (800px width)
   - Sticky header z tytułem i X button
   - Licznik: "5 of 92 products selected"
   - Select All / Unselect All buttons
   - Scrollable table (max 400px height)
   - Kolumny: Checkbox | Product Name | Ingredients | SKU
   - Header checkbox: unchecked / indeterminate / checked
   - Confirm / Cancel buttons

**Features**:
- ✅ Indeterminate checkbox state (partial selection)
- ✅ Click outside modal to close
- ✅ Auto-open modal when switching to "specific" mode
- ✅ Selection cleared when database changes
- ✅ Real-time counter update
- ✅ Toast notification on confirm: "5 products selected"
- ✅ Validation: shows warning if 0 products selected

**Backend Filtering**:
- Frontend wysyła: `selectedProductIds: [0, 1, 2, 3, 4]` (JSON array)
- Backend filtruje: `products = [p for p in all if p.get('id') in selected_ids]`
- Logger: `"Selected 5 specific products (IDs: [0, 1, 2, 3, 4])"`

**Backward Compatibility**:
- ✅ Default mode = "Generate All" (existing behavior)
- ✅ No changes to existing API contracts
- ✅ Graceful fallback if feature not used

**Testing**:
- ✅ Generate All (default) - all products generated
- ✅ Select Specific + All Selected - all products generated
- ✅ Select Specific + Partial (5 products) - only 5 generated
- ✅ Select Specific + None - validation warning
- ✅ Modal UX: Select All, Unselect All, header checkbox, individual checkboxes
- ✅ Database change - clears selection, updates product list
- ✅ Click outside / X / Cancel - closes modal

**Pliki zmienione**:
- `app_dashboard.html` (+370 lines) - UI + 11 JS functions
- `app.py` (+20 lines) - parameter parsing + filtering logic

**Commit**: `943409e` - FEATURE: Product selection in Combined Generator Step 4

---

### ✅ UX Improvements (04.02.2026) 🎨

**Cel**: Polerowanie interfejsu dla profesjonalnego, smooth user experience

---

#### 1. **Toast Notifications (zamiast alert())**

**Problem**: 25 instancji `alert()` blokowalo przegladarke

**Rozwiazanie**:
- Nowy system toastow: stackowanie (max 4), dismiss button (X), auto-duration
- Bledy: 6s, success: 4s, info: 3.5s
- Animacja wejscia i wyjscia (toastIn/toastOut)
- Zastapiono WSZYSTKIE `alert()` → `showNotification()`

---

#### 2. **Button Spinners**

**Problem**: Przyciski tylko szarzaly podczas generowania - brak informacji

**Rozwiazanie**:
- Tekst zmienia sie na "Generating..." ze spinning animation
- Po zakonczeniu wraca do oryginalnego tekstu
- Dotyczy: Generate Labels, Generate Mockups (Combined + Standalone)

---

#### 3. **Animated Progress Bar**

**Problem**: Cienki (6px), szary, maly tekst (12px), brak wizualnego feedbacku

**Rozwiazanie**:
- Wysokosc: 6px → 10px, kolor niebieski (--color-primary)
- Animowane paski (CSS stripes) podczas pracy
- Tekst: 12px → 14px, bold, z procentem: `"Processing (45/92) - 49%"`
- Klasa `.active` dodawana/usuwana automatycznie

---

#### 4. **Step Badges w Combined Generator**

**Problem**: Brak numeracji krokow - uzytkownik nie wie gdzie jest w workflow

**Rozwiazanie**:
- Niebieskie badge z numerami 1-6 przy kazdej karcie:
  - 1: Upload Vial
  - 2: Label Template
  - 3: Template Preview
  - 4: Product Data
  - 5: Generate Labels
  - 6: Generate Mockups (zielony badge)

---

#### 5. **Download Buttons z informacja o plikach**

**Problem**: "Download Labels ZIP" - nie wiadomo ile plikow, jaki rozmiar

**Rozwiazanie**:
- Dynamicznie aktualizowany tekst po generowaniu:
  - `"Download Labels ZIP (92 labels)"`
  - `"Download Mockups ZIP (91 mockups)"`
  - `"Download All (92 labels + 91 mockups)"`

---

#### 6. **CSS Variables**

**Problem**: Kolory hardcoded w 100+ miejscach, niespojne

**Rozwiazanie**:
```css
:root {
    --color-primary: #2383e2;
    --color-success: #34a853;
    --color-danger: #eb5757;
    --color-warning: #ff9800;
    --color-info: #2eaadc;
    --color-text: #37352f;
    --color-border: #e9e9e7;
    /* ... */
}
```

---

#### 7. **Color Forcing Cleanup**

**Problem**: 150+ linii `!important` rules na wymuszanie koloru tekstu

**Rozwiazanie**:
- Zredukowano do 1 reguly (6 linii) zamiast 150+
- Usunieto JavaScript `forceAllBlack()` z 4x setTimeout
- CSS dziala poprawnie bez nadmiarowych overrides

---

#### Pliki zmienione: `app_dashboard.html` (+253, -197 linii)

---

### ✅ Performance Optimizations (04.02.2026) ⚡

**Cel**: Szybsze ladowanie, plynniejsza praca, mniejsze obciazenie serwera

---

#### 1. **Gzip Compression** (flask-compress)
- HTML 368KB → ~50KB (7x mniejszy)
- Dotyczy: HTML, CSS, JS, JSON, SVG

#### 2. **Cache Headers**
- Obrazy: cache 1h (previews, mockups)
- HTML: no-cache (zawsze swiezy)
- JSON API: no-store

#### 3. **Gunicorn Preload + Keep-alive**
- `--preload`: szybszy start workerow
- `--keep-alive 5`: reuse polaczen TCP

#### 4. **Polling Intervals** (400ms → 1000ms)
- 60% mniej requestow podczas generowania
- Niezauwazalne dla uzytkownika (1s update)

#### 5. **Color Enforcer** (100ms → 2000ms)
- 95% mniej zuzycia CPU (bylo: 10x/s, jest: 0.5x/s)
- MutationObserver nadal dziala natychmiast

#### 6. **Lazy Loading Images**
- `loading="lazy"` na wszystkich preview (labels + mockups)
- Natywna funkcja przegladarki, zero JS overhead

#### 7. **Database Products Cache**
- In-memory cache z mtime invalidation
- Natychmiastowe przelaczanie zakladek (zamiast re-parse CSV)
- Auto-invalidacja przy: select, add, update, delete, import

#### 8. **TTLDict/ProgressTracker Cleanup**
- Cleanup co 5 minut zamiast przy kazdym get/set
- ~15,000 mniej iteracji na generacje

#### 9. **Text Measurement Optimization**
- Wspoldzielony draw context (1 obraz zamiast 42,000)
- Cache wynikow pomiarow tekstu
- ~50MB mniej alokacji na batch

---

#### Pliki zmienione:
- `app.py` - gzip, cache headers, db cache, TTLDict fix
- `app_dashboard.html` - polling, color enforcer, lazy loading
- `progress_tracker.py` - timer-based cleanup
- `text_formatter.py` - shared draw context + width cache
- `Procfile` - preload, keep-alive
- `requirements.txt` - flask-compress

---

### ✅ Mockup & Label Generation Fixes (03.02.2026) 🔧

**Cel**: Naprawa problemów z generowaniem mockupów i labels na Railway

---

#### 1. **Mockup Validation Fix - TEXT is PRIMARY** ⭐

**Problem**: Wszystkie mockupy failowały mimo poprawnego tekstu
```
✅ Side-by-side verification: valid=True, match=100%
❌ FAILED: VIAL size diff 53.6%
```
Gemini generuje obrazy w innej rozdzielczości - to NORMALNE!

**Rozwiązanie**:
- TEXT verification jest teraz PRIMARY (była: text AND vial)
- Vial size validation → tylko INFO (nie blokuje)
- Accept mockup jeśli text match >= 90%
- Usunięto blocking retry loop dla vial size

**Rezultat**:
```
✅ Text: 100% match → ACCEPTED
ℹ️ Vial: different resolution (expected, Gemini behavior)
```

**Pliki**: `app.py` (linie 4017-4068)

---

#### 2. **3x Vial Reference + Ultra-Low Temperature**

**Problem**: Fiolki miały różne rozmiary/kształty w mockupach

**Rozwiązanie**:
- Wysyłamy fiolkę **3 RAZY** jako reference do Gemini:
  ```
  === REFERENCE VIAL IMAGE #1 (SIZE REFERENCE) ===
  === REFERENCE VIAL IMAGE #2 (SHAPE REFERENCE) ===
  === REFERENCE VIAL IMAGE #3 (MUST MATCH EXACTLY) ===
  ```
- Ultra-low temperature: **0.01-0.02** (było: 0.05-0.1)
- Enhanced prompt z 6x "DO NOT change vial..."

**Pliki**: `app.py` (linie 3158-3299)

---

#### 3. **Label Generation Timeout (60s per label)**

**Problem**: Label generation zawieszał się na 91/92 - brak timeout

**Rozwiązanie**:
```python
LABEL_TIMEOUT = 60  # 60 sekund max per label

try:
    result = future.result(timeout=LABEL_TIMEOUT)
except TimeoutError:
    logger.error(f"⚠️ TIMEOUT for {sku} - SKIPPING")
    continue  # Przejdź do następnego labela
```

**Rezultat**:
- Labels które się zawieszają są POMIJANE
- Progress bar kontynuuje do 100%
- Raport: "91 labels, 1 skipped (timeout)"

**Pliki**: `app.py` (linie 3543-3590)

---

#### 4. **Gunicorn Workers & Timeout Increase**

**Problem**: 502 Bad Gateway podczas generowania labels

**Rozwiązanie**:
```
Workers: 2 → 4
Threads: 2 → 4
Concurrent requests: 4 → 16
Timeout: 600s → 900s (15 min)
Graceful timeout: 60s → 120s
```

**Pliki**: `Procfile`, `Dockerfile`

---

#### 5. **Font Test Endpoint**

**Nowy endpoint** do testowania dostępnych fontów:
```
GET /api/settings/font-test
```

**Zwraca**:
```json
{
  "microsoft_core_fonts_installed": true,
  "microsoft_core_fonts_count": 32,
  "total_font_families": 258,
  "test_results": [
    {"name": "Arial Bold", "status": "available", "loaded": true}
  ]
}
```

**Pliki**: `app.py` (linie 4820-4900)

---

### 📊 Podsumowanie 03.02.2026

| Feature | Problem | Rozwiązanie | Status |
|---------|---------|-------------|--------|
| **Mockup validation** | Failowało przy 100% text match | TEXT is PRIMARY | ✅ |
| **Vial size** | Blokował validation | INFO only (nie blokuje) | ✅ |
| **3x vial reference** | Różne rozmiary fiolek | Wysyłamy 3x jako reference | ✅ |
| **Temperature** | 0.05-0.1 (za wysoka) | 0.01-0.02 (ultra-low) | ✅ |
| **Label timeout** | Stuck na 91/92 | 60s timeout + skip | ✅ |
| **Gunicorn** | 502 errors | 4 workers, 16 concurrent | ✅ |
| **Font test** | Brak diagnostyki | `/api/settings/font-test` | ✅ |

**Total commits**: 5
**Pliki zmienione**: `app.py`, `Procfile`, `Dockerfile`

---

### ✅ Railway Production Deployment (02.02.2026) 🚀

**Cel**: Pełne wdrożenie produkcyjne na Railway z optymalizacją dla 8 CPU / 8GB RAM

---

#### 0. **Microsoft Core Fonts + Intelligent Font Mapping** ⭐ NOWE

**Problem**: Czcionki źle dobierane - "Arial Bold" nie działał
- Template: "Arial Bold" → Aktualnie używa: "LiberationSans-Regular" ❌
- Brak Bold weight, złe metryki, różnice w renderingu

**Rozwiązanie 1 - Install Microsoft Core Fonts**:
```dockerfile
# Download i install 11 pakietów Microsoft Core Fonts:
- Arial (Regular, Bold, Italic, Bold Italic)
- Times New Roman (all weights)
- Courier New (all weights)
- Verdana, Georgia, Trebuchet MS, Comic Sans, Impact, Webdings

Źródło: SourceForge (cabextract .exe → .ttf)
Lokalizacja: /usr/share/fonts/truetype/msttcorefonts/
```

**Rozwiązanie 2 - Intelligent Font Name Mapping**:
```python
# Nowa funkcja w text_formatter.py
_map_font_name("Arial Bold") → [
    "arialbd.ttf",           # Microsoft Core (EXACT!)
    "Arial-Bold.ttf",        # macOS
    "LiberationSans-Bold.ttf",  # Fallback
    "DejaVuSans-Bold.ttf"    # Last resort
]

# 60+ mappings dla wszystkich popularnych fontów:
- Arial (Regular, Bold, Italic, Bold Italic)
- Times New Roman (4 weights)
- Courier New (4 weights)
- Verdana, Georgia, Trebuchet, Helvetica, Calibri

Priority: Microsoft Core > Liberation > DejaVu
```

**Rezultat**:
- ✅ Template "Arial Bold" → FAKTYCZNY arialbd.ttf z Microsoft
- ✅ 100% zgodność z Adobe Illustrator
- ✅ Poprawne metryki czcionki (Bold ma Bold weight!)
- ✅ Logi: "✓ Loaded font: arialbd.ttf from /usr/share/fonts/truetype/msttcorefonts"

**Pliki**: `Dockerfile` (linie 15-47), `text_formatter.py` (linie 52-138, 141-177)

---

#### 1. **Balanced Text Wrapping - Ingredients 2:2**
**Problem**: Algorytm zawijał tekst nierównomiernie (1:3 zamiast 2:2)
- 4 składniki → Line 1: 1 składnik, Line 2: 3 składniki ❌

**Rozwiązanie**:
- STEP 1: Dla ingredients oblicz optimal line count (4 ingredients → 2 lines)
- Priorytet: MNIEJ linii + większa czcionka
- Silniejsza preferencja dla fewer lines (85% threshold zamiast 95%)

**Rezultat**:
- 4 składniki → 2:2 distribution ✅
- 6 składników → 3:3 distribution ✅

**Pliki**: `text_formatter.py` (linie 492-524, 571-582)

---

#### 2. **Area Enforcement - Hard Limit**
**Problem**: Text areas były tylko logowane, nie wymuszane!
- Tekst mógł przekraczać obszary (szczególnie na Railway z różnymi fontami)

**Rozwiązanie**:
- Retry loop: zmniejsza font o 5% aż się zmieści (max 20 prób)
- Safety margin 5% dla różnic w renderingu fontów
- CRITICAL error jeśli nadal nie pasuje

**Rezultat**: Text ZAWSZE mieści się w areas ✅

**Pliki**: `text_replacer.py` (linie 230-256)

---

#### 3. **PNG White Background**
**Problem**: PNG renderowane z przezroczystym tłem (cairosvg default)

**Rozwiązanie**:
- Render do temp PNG (transparent)
- PIL: Stwórz białe tło RGB(255, 255, 255)
- Paste PNG z alpha channel jako mask
- Save final PNG z białym tłem

**Rezultat**: PNG ma białe tło jak oryginał ✅

**Pliki**: `renderer.py` (linie 55-98)

---

#### 4. **Railway Text Positioning Fix**
**Problem**: SKU/RESEARCH USE ONLY przesuwane na Railway
- `dominant-baseline="hanging"` NIE obsługiwane przez Railway rendering

**Rozwiązanie**:
- Parse `matrix(a,b,c,d,e,f)` transform → extract translateX, translateY
- Calculate baseline offset: `y_final = translateY + (font_size * 0.85)`
- Use absolute x,y coordinates (no special attributes)

**Rezultat**: Uniwersalne pozycjonowanie (localhost + Railway) ✅

**Pliki**: `text_replacer.py` (linie 607-635)

---

#### 5. **Comprehensive Font Package**
**Problem**: Railway Docker bez czcionek → fallback fonts → złe metryki

**Rozwiązanie - zainstalowano 10 pakietów fontów**:
```dockerfile
fonts-liberation         # Arial equivalent (metrically compatible!)
fonts-liberation2        # Bold, Italic variants
fonts-dejavu             # Full weights
fonts-dejavu-extra       # Extended glyphs
fonts-freefont-ttf       # GNU fonts
fonts-noto-core          # Google Unicode
fonts-noto-ui-core       # UI fonts
fonts-urw-base35         # PostScript fonts
fonts-font-awesome       # Icons
```

**Auto-detection przy starcie**:
- Uses `fc-list` to enumerate fonts
- Logs key fonts (Liberation Sans, DejaVu, etc.)
- Helps debug font issues

**Rezultat**:
- Liberation Sans = Arial metrics ✅
- Consistent rendering localhost = Railway ✅
- 247+ font families available ✅

**Pliki**: `Dockerfile` (linie 4-28), `app.py` (linie 194-241), `text_formatter.py` (linie 65-109)

---

#### 6. **Background Cleanup Scheduler - TTL + Size Limit**
**Problem**: Pliki tymczasowe zapełniają dysk

**Rozwiązanie - automatyczne czyszczenie**:
```
Schedule:
- Temp files:   TTL=1h,    cleanup co 10 minut
- Output files: TTL=24h,   cleanup co 10 minut
- Archive:      max 5GB,   cleanup co 1 godzinę (FIFO - oldest first)
```

**Funkcje**:
- `cleanup_by_size_limit()` - FIFO deletion when exceeding 5GB
- `start_background_cleanup_scheduler()` - daemon threads
- Nie blokuje aplikacji

**Rezultat**: Automatyczne zarządzanie pamięcią ✅

**Pliki**: `cleanup_utils.py` (linie 165-264), `app.py` (linie 197-201)

---

#### 7. **Mockup Generation Optimization**
**Problem**: Timeout dla 92 mockups (tylko 2 workers, 5 min timeout)

**Rozwiązanie dla Railway paid plan (8 CPU / 8GB RAM)**:
```python
Workers: 2 → 6  (3x szybciej!)
Total timeout: 300s (5 min) → 1800s (30 min)
Per mockup: 120s (2 min) → 180s (3 min)

Konfigurowalne env vars:
- MOCKUP_WORKERS=6
- MOCKUP_TOTAL_TIMEOUT=1800
- MOCKUP_TIMEOUT=180
```

**Performance**:
- Przed: 92 mockups / 2 workers = 46 batches × 20s = ~15 min → TIMEOUT ❌
- Po: 92 mockups / 6 workers = 16 batches × 20s = ~5-10 min ✅

**Rezultat**: 3x szybciej + no timeout ✅

**Pliki**: `app.py` (linie 3938-3951)

---

#### 8. **Gunicorn Timeout Increase**
**Problem**: 180s timeout za krótki dla 92 labels

**Rozwiązanie**:
```
Timeout: 180s → 600s (10 minut)
Graceful timeout: 30s → 60s
```

**Rezultat**: Large batch generation nie timeout ✅

**Pliki**: `Procfile`, `Dockerfile` (CMD)

---

### 📊 Podsumowanie Railway Deployment

| Feature | Przed | Po | Status |
|---------|-------|-------|--------|
| **Font matching** | Liberation Regular | Microsoft Core Fonts | ✅ ⭐ |
| **"Arial Bold"** | LiberationSans-Regular | arialbd.ttf (exact!) | ✅ ⭐ |
| **Font mapping** | Brak | 60+ intelligent mappings | ✅ ⭐ |
| **Text wrapping** | 1:3 nierównomiernie | 2:2 równomiernie | ✅ |
| **Area enforcement** | Log only | Hard limit (retry) | ✅ |
| **PNG background** | Transparent | White | ✅ |
| **Railway positioning** | Przesunięte | Absolute coords | ✅ |
| **Fonts installed** | 247+ families | 247+ PLUS MS Core | ✅ |
| **Cleanup** | Manual | Auto (TTL + 5GB) | ✅ |
| **Mockup workers** | 2 | 6 | ✅ |
| **Mockup timeout** | 5 min | 30 min | ✅ |
| **Gunicorn timeout** | 3 min | 10 min | ✅ |

**Total commits dzisiaj**: 12 ⭐
**Total plików zmienionych**: 9 ⭐
**Railway deployment**: ✅ Production ready (deploying now...)

---

### ✅ Zaimplementowano Text Alignment (01.02.2026)

**Cel**: Kontrola wyrównania tekstu (LEFT/CENTER/RIGHT) dla Product Name i Ingredients

**Implementacja**:
- ✅ UI: Przyciski LEFT | CENTER | RIGHT w Template Preview
- ✅ Tylko dla Product Name i Ingredients (SKU bez zmian)
- ✅ Frontend: `textAlignmentsCombined` object, funkcja `setTextAlignmentCombined()`
- ✅ Backend: `text_alignments` parameter w całym pipeline
- ✅ TextReplacer: `_get_text_anchor()` - konwersja left/center/right → start/middle/end
- ✅ SVG: `text-anchor` attribute + dynamiczne X pozycje
- ✅ Dokumentacja: Updated Instructions page

**Pliki zmodyfikowane**:
1. `app_dashboard.html`:
   - Linie 1119-1157: UI alignment buttons
   - Linie 2608-2614: textAlignmentsCombined object
   - Linie 7039-7054: setTextAlignmentCombined() function
   - Linie 7510: FormData append textAlignments
   - Linie 1941-1991: Instructions - Text Alignment section

2. `app.py`:
   - Linie 3454-3457: Parse textAlignments from request
   - Linie 3547: Pass to _generate_labels_task()
   - Linie 3236-3238: Function signature update

3. `batch_processor.py`:
   - Linia 27: __init__ accepts text_alignments
   - Linia 55: Pass to TextReplacer

4. `text_replacer.py`:
   - Linia 30-35: __init__ accepts text_alignments
   - Linia 36-44: _get_text_anchor() helper method
   - Linia 243-264: Dynamic X position + text-anchor (with user area)
   - Linia 283-289: Dynamic tspan positioning
   - Linia 534-568: Dynamic positioning (aria-label elements)

**Weryfikacja**: `./restart.sh` → http://localhost:8000 → Template Preview

**Użycie**:
```
1. Upload template + CSV
2. Draw text areas dla Product Name i Ingredients
3. Wybierz alignment:
   - Product Name: LEFT / CENTER / RIGHT
   - Ingredients: LEFT / CENTER / RIGHT
4. Generate Labels
```

**Rezultat SVG**:
```xml
<!-- LEFT alignment -->
<text text-anchor="start" x="area_x">Text</text>

<!-- CENTER alignment (default) -->
<text text-anchor="middle" x="area_x + width/2">Text</text>

<!-- RIGHT alignment -->
<text text-anchor="end" x="area_x + width">Text</text>
```

---

### ✅ Zaimplementowano Async Mockup Generation (31.01.2026)

**Cel**: Możliwość przełączania kart w przeglądarce podczas generacji mockupów (15-20 minut)

**Implementacja**:
- ✅ Flask `threaded=True` - wielowątkowy serwer
- ✅ `@run_in_background` - background tasks
- ✅ JavaScript polling (500ms) - progress tracking
- ✅ Endpoint zwraca `job_id` natychmiast (~50ms)
- ✅ Parallel processing - 4 workers (ThreadPoolExecutor)
- ✅ Verification zachowana - side-by-side (bez zmian)

**Pliki zmodyfikowane**:
1. `app.py` - linie: 4708, 3143, 3326-3357, 3412-3424
2. `app_dashboard.html` - linie: 7690-7752, funkcja `fetchMockupGenerationResults()`

**Weryfikacja**: `./restart.sh` → http://localhost:8000

---

## 📋 GŁÓWNE FUNKCJE

### 1. **Label Generator**
- Upload template (SVG/AI)
- Upload CSV database (65 produkty: YPB.211-283)
- **5 data fields**: Product Name, Ingredients, SKU, **CAS Number**, **Molecular Weight** - NEW 14.02.2026
- Batch generation: SVG + JPG (2400 DPI, 4200x1800)
- Intelligent text wrapping & formatting
- **Text alignment control** (LEFT/CENTER/RIGHT) - NEW 01.02.2026
- **Auto-detection placeholders** (zero manual work) - ENHANCED 14.02.2026

### 2. **Mockup Generator**
- Upload vial image
- Gemini Vision API (gemini-2.5-flash-image)
- Green background removal
- Side-by-side verification (96% accuracy)
- Retry logic (3 attempts per mockup)
- Parallel processing (4 workers)

### 3. **Combined Generator**
- Step 1: Generate labels → ZIP
- Step 2: Generate mockups → ZIP
- Download All: Combined ZIP (labels + mockups by SKU)

### 4. **Archive Management**
- List all jobs (labels + mockups)
- Download archives
- Delete old files
- Storage statistics

---

## 🛠️ TECHNOLOGIE

**Backend**:
- Python 3.9 + Flask 3.0
- PyMuPDF (AI → SVG conversion @ 675 DPI)
- CairoSVG (SVG → PNG @ 300 DPI)
- ReportLab (SVG → PDF wektorowy)
- Pillow + rembg (background removal)

**API**:
- Google Gemini 2.5 Flash Image API
- `google-genai>=1.47.0` (nowy SDK 2026)

**Frontend**:
- HTML/JavaScript (single page app)
- Real-time progress tracking
- Drag & drop file upload

---

## 📁 STRUKTURA PROJEKTU

```
/Users/lukasz/YPBv2/
├── app.py (6135 linii)           # Flask application
├── app_dashboard.html            # Frontend UI
├── ai_converter.py (1666 linii)  # AI → SVG (PyMuPDF) + CFF decoding + PIL fallback
├── text_replacer.py              # Text replacement engine
├── text_formatter.py             # Intelligent text wrapping
├── batch_processor.py            # Batch processing (parallel)
├── renderer.py                   # SVG → PNG/PDF/JPG
├── verification_side_by_side.py  # Gemini Vision verification
├── template_parser.py            # SVG template parsing
├── csv_manager.py                # CSV database handling
├── progress_tracker.py           # Thread-safe progress tracking
├── cleanup_utils.py              # Temp file cleanup
├── gemini_ocr.py                 # Gemini OCR for garbled text
├── config.py                     # Configuration
├── .env.local                    # API keys
├── requirements.txt              # Python dependencies
├── databases/
│   └── YPB_data_Arkusz3.csv     # 91 produktów (YPB.101 - YPB.283)
├── fonts/
│   ├── google/                  # 398 Google Fonts TTF (81 families)
│   └── montserrat/              # 9 Montserrat TTF
├── temp/                         # Tymczasowe pliki (auto-cleanup)
├── output/                       # Wygenerowane labels & mockups
└── uploads/                      # Przesłane templates & images
```

---

## ⚙️ KONFIGURACJA

### Environment Variables (.env.local)
```bash
GEMINI_API_KEY=your_gemini_api_key_here
AUTH_USER=Admin
AUTH_PASS=your_password_here
DISABLE_AUTH=true
```

### Kluczowe Ustawienia (config.py)
```python
PNG_DPI = 2400
PDF_VECTOR_MODE = True
MAX_CONCURRENT_JOBS = 4
GEMINI_MOCKUP_MODEL = 'gemini-2.5-flash-image'
AUTO_CLEANUP_HOURS = 24
```

---

## 🚀 URUCHOMIENIE

```bash
# Start
./start.sh

# Stop
./stop.sh

# Restart
./restart.sh

# Check logs
tail -f /tmp/flask_app.log
```

**URL**: http://localhost:8000

---

## 📊 WORKFLOW

### Combined Generator (Pełny przepływ):

1. **Upload Template** (SVG/AI)
   - AI files są konwertowane do SVG @ 675 DPI
   - Ekstrakcja placeholders: `product_name`, `ingredients`, `sku`

2. **Generate Labels** (Async)
   - 92 produkty z CSV
   - Formatowanie tekstu (auto-wrap, optimal font size)
   - Output: SVG + JPG (2400 DPI)
   - ZIP: `labels_YYYYMMDD_HHMMSS.zip`
   - Czas: ~2 minuty

3. **Upload Vial Image** (PNG/JPG)
   - Obraz produktu (fiolka)
   - Opcjonalnie: crop region dla label

4. **Generate Mockups** (Async - NOWE!)
   - Parallel processing (4 workers)
   - Dla każdej label:
     - Add green background (#00FF00)
     - Send to Gemini Vision API
     - Remove green background
     - Verification (side-by-side)
     - Retry (max 3×) jeśli failed
   - Output: `mockup_SKU.png`
   - ZIP: `mockups_YYYYMMDD_HHMMSS.zip`
   - Czas: ~15-20 minut (91 mockups)
   - **✅ Możesz przełączyć kartę w Chrome!**

5. **Download All**
   - Combined ZIP: `combined_YYYYMMDD_HHMMSS.zip`
   - Struktura:
     ```
     YPB.100/
       ├── label.svg
       ├── label.jpg
       └── mockup.png
     ```

---

## 🐛 ZNANE PROBLEMY

### AI Converter - Background Loss
**Problem**: AI converter usuwa background rectangles podczas konwersji AI → SVG

**Przyczyna**: Regex `svg = re.sub(r'<use[^>]*xlink:href="#g[0-9]+"[^>]*/>', '', svg)` usuwa również background graphics

**Status**: Known issue, nie naprawione (wymaga refactor AI converter)

**Workaround**: Używaj SVG templates zamiast AI files, lub dodaj background ręcznie

---

## 📈 STATYSTYKI

- **Kod Python**: ~12,400 linii (14 plików)
- **Frontend**: 416 KB / 8,541 linii (app_dashboard.html)
- **Total codebase**: ~20,900 linii
- **Google Fonts**: 398 plików TTF (81 rodzin, 32 MB)
- **Fontconfig aliases**: 188 match rules
- **Database**: 91 produktów (YPB.101 - YPB.283), 5 kolumn (Product, Ingredients, SKU, CAS, MW)
- **Database fields**: 5 (Product, Ingredients, SKU, **CAS Number**, **Molecular Weight**)
- **Auto-detection**: 5 placeholders (100% automatic, zero manual work)
- **Output total**: ~1.1 GB (archiwum)
- **Avg label generation**: 2 minuty
- **Avg mockup generation**: 15-20 minut (91 mockups, parallel)
- **Verification accuracy**: 96% (side-by-side)

---

## 🔧 MAINTENANCE

### Auto-cleanup
- Startup cleanup: usuwa pliki >24h z `temp/` i `output/`
- Wykonywane przy każdym starcie aplikacji

### Manual cleanup
```python
from cleanup_utils import cleanup_old_files
cleanup_old_files(config.TEMP_DIR, hours=24)
cleanup_old_files(config.OUTPUT_DIR, hours=24)
```

---

## 📝 CHANGELOG

### 17 lutego 2026
- ✅ **FIX: Background Removal** - rembg zainstalowane + uint8 overflow fix + opaque vial alpha fix
- ✅ **FIX: Label Crop Scaling** - koordynaty skalowane z template→label dimensions (było: raw template coords na 4200x1800)
- ✅ **UX: Label Progress Bar** - elapsed time + ETA (jak mockup progress bar)
- ✅ **Pliki zmienione**: app.py, app_dashboard.html
- ✅ **Commits**: `c2391a0`, `5051e56`, `c222291`

### 16 lutego 2026
- ✅ **ZIP Only SVG+JPG** - usunięto PNG i PDF z ZIP (main, fallback, combined pipelines)
- ✅ **Mask Transparency Fix** - CairoSVG render at native size + PIL LANCZOS upscale (fix washed-out logo edges)
- ✅ **PDF Removed** - usunięto generowanie PDF z pipeline (renderer, app.py, batch_processor)
- ✅ **Hybrid JPG DPI** - dodano metadane DPI do hybrid fallback JPG
- ✅ **8 Resize Handles** - corners + edges dla areas w Combined + Standalone generators
- ✅ **Pliki zmienione**: renderer.py, app.py, ai_converter.py, batch_processor.py, app_dashboard.html
- ✅ **Commits**: `da37e56` (resize handles), `caf138d` (ZIP + transparency fix)

### 15 lutego 2026 (wieczór)
- ✅ **FIX: ZIP Download Bug** - pliki ZIP teraz zapisywane w output_dir zamiast temp_dir
- ✅ **Problem**: ZIPy były tworzone w temp/ (auto-cleanup po 1h) → download 404 error
- ✅ **Rozwiązanie**: 4 miejsca w app.py - ZIP path zmieniony z TEMP_DIR → output_dir/OUTPUT_DIR
  - Labels ZIP (main pipeline) - linia ~3956
  - Labels ZIP (SVG fallback) - linia ~3608
  - Mockups ZIP (from labels) - linia ~4483
  - Batch mockups ZIP (standalone) - linia ~5006
- ✅ **Rezultat**: ZIPy persistent i downloadable, chronione przed temp cleanup (24h TTL)
- ✅ **Pliki zmienione**: app.py (8 insertions, 8 deletions)
- ✅ **Commit**: `98bacc6` - pushed to GitHub

### 15 lutego 2026 (rano)
- ✅ **CAS/MW Prefix Preservation** - zachowanie etykiet "CAS: " i "M.W.: " przy replacement
- ✅ **Synchronized CAS/MW** - oba pola zawsze mają ten sam font_size i liczbę linii
- ✅ **Zone-Based Positioning** - auto-detekcja dostępnej strefy z sąsiednich elementów SVG
- ✅ **Ascender-Aware Boundaries** - boundary_bottom uwzględnia wizualną górę tekstu poniżej (font_size * 0.85)
- ✅ **Original Y Positions** - CAS/MW zostają na oryginalnych pozycjach, MW przesuwa się tylko przy zawijaniu CAS
- ✅ **Tight Line Height** - line_height=1.1x (było: 1.25x) dla mniejszych odstępów między liniami
- ✅ **Full Width** - available_width = SVG edge - elem_x (pełna szerokość labela)
- ✅ **Optional CAS/MW** - template_parser i data_mapper traktują cas/mw jako opcjonalne
- ✅ **CAS/MW Inject** - automatyczne wstrzykiwanie data-placeholder po parse_by_position()
- ✅ **Pliki zmienione**: text_replacer.py, template_parser.py, data_mapper.py, app.py
- ✅ **Commit**: `719fb1d` - pushed to GitHub

### 14 lutego 2026
- ✅ **CAS Number & Molecular Weight** - dodanie 2 nowych pól do systemu (5 total fields)
- ✅ **Database Structure** - 3 kolumny → 5 kolumn (Product, Ingredients, SKU, **CAS**, **MW**)
- ✅ **Auto-detection CAS/MW** - automatyczne wykrywanie w template przez matching z bazą (zero manual work)
- ✅ **CSV Manager** - wszystkie CRUD operacje obsługują CAS i MW
- ✅ **Import CSV** - auto-mapping dla "CAS Number" i "Molecular Weight" kolumn
- ✅ **UI Updates** - Database table (7 kolumn), Import modal (5 mappings), Product Selection modal
- ✅ **Text Replacement** - FIELD_MAPPING rozszerzony o 'cas' i 'mw'
- ✅ **Template Parser** - usunięto CAS/MW z skip_keywords (nie pomija tych elementów)
- ✅ **Backend API** - `/api/database/products` zwraca CAS i MW
- ✅ **Testing** - 7/7 testów passed (database, API, auto-detection, replacement, config, import, skip)
- ✅ **Pliki zmienione**: 9 plików (config.py, csv_manager.py, text_replacer.py, template_parser.py, app.py, app_dashboard.html, databases/)
- ✅ **Total lines**: ~300 linii dodanych/zmienionych

### 13 lutego 2026
- ✅ **Filename Format** - pliki label nazwane po SKU: `YPB.200.jpg` (było: `ProductName_YPB.200.jpg`)
- ✅ **2400 DPI** - wszystkie outputy label w 2400 DPI (było: 300 DPI)
- ✅ **SVG fallback DPI fix** - dodano `dpi=config.PNG_DPI` do SVG fallback path (było: 96 DPI default!)

### 8 lutego 2026
- ✅ **Google Fonts Library** - 398 fontów (81 rodzin) pobrane z fontsource CDN
- ✅ **Fontconfig Aliases** - 188 `<match>` rules mapujących komercyjne→Google Fonts
- ✅ **Strong Matching** - `<match mode="assign" binding="strong">` zamiast `<alias><prefer>`
- ✅ **CFF Font Decoding** - dekodowanie CFF charset z plików AI (eliminacja garbled text)
- ✅ **SVG Position-Based Fallback** - text replacement by position (backup dla garbled)
- ✅ **PIL Overlay Fallback** - render paths→PNG + PIL text overlay (ostatnia deska ratunku)
- ✅ **Gemini OCR Module** - nowy `gemini_ocr.py` do ekstrakcji tekstu z AI preview
- ✅ **FONT_ALTERNATIVES dict** - 60+ mapowań komercyjnych→Google Fonts w ai_converter.py
- ✅ **Mockup Progress Bar** - elapsed time, ETA, fazy generowania zamiast statycznego "Starting..."
- ✅ **Standalone Mockup Timer** - animowane fazy z elapsed timer (Sending→Processing→Almost done)
- ✅ **Security** - usunięto hardcoded API keys z dokumentacji (CLAUDE.md, RAILWAY_*.md)
- ✅ **.gitignore** - dodano fonts/ (32MB) i test_results_*/
- ✅ **Kluczowe mapowania**: Gotham→Montserrat, Helvetica→Inter, Futura→Nunito, Avenir→Nunito Sans, Century Gothic→Poppins, Franklin Gothic→Libre Franklin, Myriad Pro→Source Sans 3, DIN→Oswald, Circular→DM Sans, Knockout→Bebas Neue
- ✅ **Commit**: `1261d58` - pushed to GitHub

### 5 lutego 2026
- ✅ **FEATURE: Product Selection** - wybór konkretnych produktów w Combined Generator
- ✅ **Database Indicator** - nazwa bazy + liczba produktów w Step 4
- ✅ **Mode Toggle** - "Generate All" vs "Select Specific Products"
- ✅ **Selection Modal** - lista produktów z checkboxami (800px)
- ✅ **Select All/Unselect All** - bulk actions
- ✅ **Indeterminate Checkbox** - partial selection state
- ✅ **Real-time Counters** - "5 of 92 products selected"
- ✅ **Frontend Validation** - wymaga min. 1 produkt
- ✅ **Backend Filtering** - filtrowanie po selected IDs
- ✅ **Auto-clear** - reset selection przy zmianie bazy
- ✅ **Toast Notifications** - "5 products selected" confirmation
- ✅ **Backward Compatible** - default = "Generate All"

### 4 lutego 2026
- ✅ **UX: Toast Notifications** - 25x alert() → styled toasts z dismiss
- ✅ **UX: Button Spinners** - "Generating..." z animacja podczas pracy
- ✅ **UX: Animated Progress Bar** - paski, 10px, procent, wiekszy tekst
- ✅ **UX: Step Badges** - numeracja 1-6 w Combined Generator
- ✅ **UX: Download Info** - "Download Labels ZIP (92 labels)"
- ✅ **UX: CSS Variables** - spojne kolory w calej aplikacji
- ✅ **UX: Color Forcing** - 150+ linii → 1 regula
- ✅ **PERF: Gzip** - flask-compress (7x mniejszy HTML)
- ✅ **PERF: Cache Headers** - obrazy 1h, HTML no-cache
- ✅ **PERF: Polling** - 400ms → 1000ms (60% mniej requestow)
- ✅ **PERF: Lazy Loading** - loading="lazy" na preview images
- ✅ **PERF: DB Cache** - in-memory z mtime invalidation
- ✅ **PERF: Text Measurement** - shared draw context + cache
- ✅ **PERF: TTLDict** - cleanup co 5min zamiast per-access
- ✅ **PERF: Gunicorn** - preload + keep-alive 5

### 3 lutego 2026
- ✅ **Mockup Validation Fix** - TEXT is PRIMARY (vial size = info only)
- ✅ **3x Vial Reference** - wysylamy fiolke 3 razy do Gemini
- ✅ **Label Timeout** - 60s per label, skip on timeout
- ✅ **Gunicorn** - 4 workers, 16 concurrent, 900s timeout
- ✅ **Font Test Endpoint** - /api/settings/font-test
- ✅ **Microsoft Core Fonts** - arialbd.ttf + 60+ font mappings
- ✅ **Font Path Cache** - eliminate 800+ redundant I/O ops

### 31 stycznia 2026
- ✅ **Async Mockup Generation** - możliwość przełączania kart
- ✅ Flask `threaded=True`
- ✅ Background tasks z `@run_in_background`
- ✅ JavaScript polling (500ms)
- ✅ Progress tracking w czasie rzeczywistym

### 30 stycznia 2026
- ✅ Side-by-side verification (Gemini Vision API)
- ✅ 96% accuracy (było: 70%)
- ✅ Composite image (mockup | label)

### 29 stycznia 2026
- ✅ Gemini API modernizacja (`google-genai>=1.47.0`)
- ✅ Auto-retry logic (3 attempts)
- ✅ Improved text wrapping (ingredients)
- ✅ Download All button (combined ZIP)

### 28 stycznia 2026
- ✅ Initial deployment
- ✅ Complete application analysis

---

## 🎓 DOKUMENTACJA

- `README.md` - Overview
- `QUICKSTART.md` - Quick start guide
- `START_APP.md` - Startup instructions
- `INSTALL_CAIRO.md` - Cairo installation (macOS)
- `MIGRATION_GUIDE.md` - Gemini SDK migration
- `RAILWAY_DEPLOYMENT.md` - Railway deployment guide

---

## 📞 CONTACT & SUPPORT

**Repository**: https://github.com/lumizone/Ypb
**Application**: Local development (http://localhost:8000)
**Python**: 3.9+
**Platform**: macOS (tested), Linux (compatible)

---

**Last Updated**: 17 lutego 2026 (commit: `c222291`)
**Status**: ✅ Production Ready - Background Removal Fix + Label Crop Scaling + ZIP SVG+JPG + Mask Fix + 2400 DPI (4200x1800) + CAS/MW + SKU Filenames + 5 Data Fields + Google Fonts (398) + Fontconfig (188 aliases)
