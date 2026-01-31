# Automatyzacja Inkscape - Konwersja AI → SVG przez CLI/API

## 🎯 CEL
Stworzenie aplikacji w Cursor, która automatycznie konwertuje pliki `.ai` do `.svg` z użyciem Inkscape CLI.

---

## 📋 WYMAGANIA

### 1. Zainstaluj Inkscape
```bash
# macOS
brew install inkscape

# Ubuntu/Debian
sudo apt update
sudo apt install inkscape

# Windows (przez Chocolatey)
choco install inkscape

# Lub pobierz z: https://inkscape.org/release/
```

### 2. Sprawdź instalację
```bash
inkscape --version
# Powinno zwrócić: Inkscape 1.4.x (lub nowsze)
```

---

## 🔧 PODSTAWOWE KOMENDY INKSCAPE CLI

### Konwersja AI → SVG (PODSTAWOWA)
```bash
inkscape input.ai \
  --export-type=svg \
  --export-filename=output.svg
```

### Konwersja AI → SVG (PROFESJONALNA - z tekstem jako ścieżki)
```bash
inkscape input.ai \
  --export-type=svg \
  --export-text-to-path \
  --export-plain-svg \
  --export-dpi=300 \
  --export-filename=output.svg
```

### Wyjaśnienie flag:
- `--export-type=svg` - eksport do SVG
- `--export-text-to-path` - **konwertuje CAŁY tekst na ścieżki** (NAJWAŻNIEJSZE!)
- `--export-plain-svg` - czysty SVG bez metadanych Inkscape
- `--export-dpi=300` - wysoka rozdzielczość (dla ostrości)
- `--export-filename=output.svg` - nazwa pliku wyjściowego

---

## 💻 INTEGRACJA Z NODE.JS / TYPESCRIPT

### Struktura projektu
```
project/
├── src/
│   ├── index.ts           # Główny plik
│   ├── converter.ts       # Logika konwersji
│   └── utils.ts           # Pomocnicze funkcje
├── input/                 # Pliki .ai do konwersji
├── output/                # Wygenerowane .svg
├── package.json
└── tsconfig.json
```

---

### package.json
```json
{
  "name": "ai-to-svg-converter",
  "version": "1.0.0",
  "type": "module",
  "scripts": {
    "dev": "tsx watch src/index.ts",
    "build": "tsc",
    "start": "node dist/index.js",
    "convert": "tsx src/index.ts"
  },
  "dependencies": {
    "express": "^4.18.2",
    "multer": "^1.4.5-lts.1"
  },
  "devDependencies": {
    "@types/express": "^4.17.21",
    "@types/multer": "^1.4.11",
    "@types/node": "^20.11.5",
    "tsx": "^4.7.0",
    "typescript": "^5.3.3"
  }
}
```

---

### src/converter.ts
```typescript
import { exec } from 'child_process';
import { promisify } from 'util';
import path from 'path';
import fs from 'fs/promises';

const execAsync = promisify(exec);

export interface ConversionOptions {
  textToPath?: boolean;      // Konwertuj tekst na ścieżki
  plainSvg?: boolean;         // Czysty SVG bez metadanych
  dpi?: number;               // Rozdzielczość (domyślnie 300)
  removeMetadata?: boolean;   // Usuń metadane Inkscape
}

export class InkscapeConverter {
  private inkscapePath: string;

  constructor(inkscapePath: string = 'inkscape') {
    this.inkscapePath = inkscapePath;
  }

  /**
   * Sprawdź czy Inkscape jest zainstalowany
   */
  async checkInkscape(): Promise<boolean> {
    try {
      const { stdout } = await execAsync(`${this.inkscapePath} --version`);
      console.log('✅ Inkscape znaleziony:', stdout.trim());
      return true;
    } catch (error) {
      console.error('❌ Inkscape nie jest zainstalowany!');
      return false;
    }
  }

  /**
   * Konwertuj AI do SVG
   */
  async convert(
    inputPath: string,
    outputPath: string,
    options: ConversionOptions = {}
  ): Promise<{ success: boolean; outputPath?: string; error?: string }> {
    try {
      // Sprawdź czy plik wejściowy istnieje
      await fs.access(inputPath);

      // Domyślne opcje
      const {
        textToPath = true,
        plainSvg = true,
        dpi = 300,
        removeMetadata = true
      } = options;

      // Buduj komendę
      const args = [
        `"${inputPath}"`,
        '--export-type=svg',
        textToPath ? '--export-text-to-path' : '',
        plainSvg ? '--export-plain-svg' : '',
        `--export-dpi=${dpi}`,
        `--export-filename="${outputPath}"`
      ].filter(Boolean).join(' ');

      const command = `${this.inkscapePath} ${args}`;

      console.log('🔄 Konwersja:', path.basename(inputPath));
      console.log('📝 Komenda:', command);

      // Wykonaj konwersję
      const { stdout, stderr } = await execAsync(command);

      if (stderr && !stderr.includes('WARNING')) {
        throw new Error(stderr);
      }

      // Sprawdź czy plik wyjściowy został utworzony
      await fs.access(outputPath);

      console.log('✅ Konwersja zakończona:', path.basename(outputPath));

      return {
        success: true,
        outputPath
      };

    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : 'Nieznany błąd';
      console.error('❌ Błąd konwersji:', errorMessage);
      
      return {
        success: false,
        error: errorMessage
      };
    }
  }

  /**
   * Konwertuj wiele plików naraz
   */
  async convertBatch(
    inputDir: string,
    outputDir: string,
    options: ConversionOptions = {}
  ): Promise<{ total: number; success: number; failed: number }> {
    const files = await fs.readdir(inputDir);
    const aiFiles = files.filter(f => f.toLowerCase().endsWith('.ai'));

    let success = 0;
    let failed = 0;

    // Upewnij się, że katalog wyjściowy istnieje
    await fs.mkdir(outputDir, { recursive: true });

    for (const file of aiFiles) {
      const inputPath = path.join(inputDir, file);
      const outputPath = path.join(outputDir, file.replace(/\.ai$/i, '.svg'));

      const result = await this.convert(inputPath, outputPath, options);

      if (result.success) {
        success++;
      } else {
        failed++;
      }
    }

    return { total: aiFiles.length, success, failed };
  }

  /**
   * Pobierz informacje o pliku SVG
   */
  async getSvgInfo(svgPath: string): Promise<{
    hasText: boolean;
    hasPaths: boolean;
    textCount: number;
    pathCount: number;
  }> {
    try {
      const content = await fs.readFile(svgPath, 'utf-8');
      
      const textCount = (content.match(/<text/g) || []).length;
      const pathCount = (content.match(/<path/g) || []).length;

      return {
        hasText: textCount > 0,
        hasPaths: pathCount > 0,
        textCount,
        pathCount
      };
    } catch (error) {
      throw new Error(`Nie można odczytać pliku: ${error}`);
    }
  }
}
```

---

### src/index.ts
```typescript
import { InkscapeConverter } from './converter.js';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

async function main() {
  const converter = new InkscapeConverter();

  // Sprawdź czy Inkscape jest zainstalowany
  const isInstalled = await converter.checkInkscape();
  if (!isInstalled) {
    console.error('Zainstaluj Inkscape: https://inkscape.org/');
    process.exit(1);
  }

  // Przykład 1: Konwersja pojedynczego pliku
  const inputFile = path.join(__dirname, '../input/example.ai');
  const outputFile = path.join(__dirname, '../output/example.svg');

  const result = await converter.convert(inputFile, outputFile, {
    textToPath: true,
    plainSvg: true,
    dpi: 300
  });

  if (result.success) {
    // Sprawdź wynik
    const info = await converter.getSvgInfo(result.outputPath!);
    console.log('📊 Statystyki SVG:', info);
  }

  // Przykład 2: Konwersja wielu plików
  const inputDir = path.join(__dirname, '../input');
  const outputDir = path.join(__dirname, '../output');

  const batchResult = await converter.convertBatch(inputDir, outputDir, {
    textToPath: true,
    plainSvg: true,
    dpi: 300
  });

  console.log('📦 Batch konwersja:');
  console.log(`  Wszystkie: ${batchResult.total}`);
  console.log(`  Sukces: ${batchResult.success}`);
  console.log(`  Błędy: ${batchResult.failed}`);
}

main().catch(console.error);
```

---

## 🌐 API SERVER (Express)

### src/api.ts
```typescript
import express from 'express';
import multer from 'multer';
import { InkscapeConverter } from './converter.js';
import path from 'path';
import fs from 'fs/promises';

const app = express();
const converter = new InkscapeConverter();

// Konfiguracja multer do upload plików
const upload = multer({
  dest: 'uploads/',
  fileFilter: (req, file, cb) => {
    if (file.originalname.toLowerCase().endsWith('.ai')) {
      cb(null, true);
    } else {
      cb(new Error('Tylko pliki .ai są dozwolone'));
    }
  }
});

// Endpoint do konwersji
app.post('/convert', upload.single('file'), async (req, res) => {
  try {
    if (!req.file) {
      return res.status(400).json({ error: 'Brak pliku' });
    }

    const inputPath = req.file.path;
    const outputPath = inputPath.replace(/\.ai$/i, '.svg');

    const result = await converter.convert(inputPath, outputPath, {
      textToPath: true,
      plainSvg: true,
      dpi: 300
    });

    if (!result.success) {
      return res.status(500).json({ error: result.error });
    }

    // Zwróć plik SVG
    res.download(result.outputPath!, async (err) => {
      if (err) {
        console.error('Błąd wysyłania pliku:', err);
      }
      
      // Usuń tymczasowe pliki
      await fs.unlink(inputPath).catch(() => {});
      await fs.unlink(result.outputPath!).catch(() => {});
    });

  } catch (error) {
    console.error('Błąd API:', error);
    res.status(500).json({ 
      error: error instanceof Error ? error.message : 'Nieznany błąd' 
    });
  }
});

// Endpoint do batch conversion
app.post('/convert-batch', upload.array('files', 10), async (req, res) => {
  try {
    const files = req.files as Express.Multer.File[];
    
    if (!files || files.length === 0) {
      return res.status(400).json({ error: 'Brak plików' });
    }

    const results = [];

    for (const file of files) {
      const inputPath = file.path;
      const outputPath = inputPath.replace(/\.ai$/i, '.svg');

      const result = await converter.convert(inputPath, outputPath, {
        textToPath: true,
        plainSvg: true,
        dpi: 300
      });

      results.push({
        filename: file.originalname,
        success: result.success,
        error: result.error
      });

      // Usuń plik wejściowy
      await fs.unlink(inputPath).catch(() => {});
    }

    res.json({ results });

  } catch (error) {
    console.error('Błąd batch API:', error);
    res.status(500).json({ 
      error: error instanceof Error ? error.message : 'Nieznany błąd' 
    });
  }
});

// Health check
app.get('/health', async (req, res) => {
  const isInstalled = await converter.checkInkscape();
  res.json({ 
    status: 'ok',
    inkscape: isInstalled 
  });
});

const PORT = process.env.PORT || 3000;

app.listen(PORT, () => {
  console.log(`🚀 Server uruchomiony na http://localhost:${PORT}`);
});
```

---

## 🧪 TESTOWANIE

### Test konwersji
```typescript
// test.ts
import { InkscapeConverter } from './src/converter.js';

const converter = new InkscapeConverter();

// Test 1: Sprawdź Inkscape
await converter.checkInkscape();

// Test 2: Konwertuj plik
const result = await converter.convert(
  './input/test.ai',
  './output/test.svg',
  { textToPath: true }
);

console.log(result);

// Test 3: Sprawdź wynik
const info = await converter.getSvgInfo('./output/test.svg');
console.log('Tekst jako <text>:', info.textCount);
console.log('Ścieżki <path>:', info.pathCount);
```

---

## 📦 UŻYCIE API (curl)

### Konwersja pojedynczego pliku
```bash
curl -X POST \
  -F "file=@input.ai" \
  http://localhost:3000/convert \
  --output output.svg
```

### Batch konwersja
```bash
curl -X POST \
  -F "files=@file1.ai" \
  -F "files=@file2.ai" \
  -F "files=@file3.ai" \
  http://localhost:3000/convert-batch
```

---

## 🔥 ZAAWANSOWANE OPCJE

### Dodatkowe flagi Inkscape

#### Export do różnych formatów
```bash
# PNG
inkscape input.ai \
  --export-type=png \
  --export-dpi=300 \
  --export-filename=output.png

# PDF
inkscape input.ai \
  --export-type=pdf \
  --export-filename=output.pdf
```

#### Manipulacja elementami
```bash
# Usuń konkretny obiekt po ID
inkscape input.svg \
  --actions="select-by-id:object-id;delete" \
  --export-filename=output.svg

# Zmień kolor
inkscape input.svg \
  --actions="select-all;object-fill:#FF0000" \
  --export-filename=output.svg
```

#### Actions (zaawansowane)
```typescript
async executeAction(inputPath: string, outputPath: string, action: string) {
  const command = `inkscape "${inputPath}" \
    --actions="${action}" \
    --export-filename="${outputPath}"`;
  
  await execAsync(command);
}

// Przykład użycia:
await converter.executeAction(
  'input.svg',
  'output.svg',
  'select-all;object-to-path'
);
```

---

## ⚙️ KONFIGURACJA (config.ts)

```typescript
export const config = {
  inkscape: {
    path: process.env.INKSCAPE_PATH || 'inkscape',
    defaultDpi: 300,
    defaultOptions: {
      textToPath: true,
      plainSvg: true,
      removeMetadata: true
    }
  },
  paths: {
    input: './input',
    output: './output',
    temp: './temp'
  },
  api: {
    port: process.env.PORT || 3000,
    maxFileSize: 50 * 1024 * 1024, // 50MB
    maxFiles: 10
  }
};
```

---

## 🚀 URUCHOMIENIE

```bash
# Instalacja zależności
npm install

# Rozwój (watch mode)
npm run dev

# Build
npm run build

# Produkcja
npm start

# Konwersja (bez servera)
npm run convert
```

---

## 📋 CHECKLIST

- [x] Zainstaluj Inkscape
- [x] Stwórz projekt w Cursor
- [x] Zaimplementuj `converter.ts`
- [x] Dodaj API endpoints (opcjonalnie)
- [x] Testuj konwersję
- [x] Sprawdź czy tekst jest jako `<path>`
- [x] Deploy (opcjonalnie)

---

## 💡 NAJWAŻNIEJSZE

### Komenda do konwersji AI → SVG (PROFESJONALNA)
```bash
inkscape input.ai \
  --export-type=svg \
  --export-text-to-path \
  --export-plain-svg \
  --export-dpi=300 \
  --export-filename=output.svg
```

### TypeScript przykład
```typescript
const converter = new InkscapeConverter();

const result = await converter.convert(
  './input/label.ai',
  './output/label.svg',
  {
    textToPath: true,    // Tekst jako ścieżki
    plainSvg: true,      // Czysty SVG
    dpi: 300             // Wysoka jakość
  }
);

if (result.success) {
  console.log('✅ Gotowe!');
}
```

---

## 🎉 GOTOWE!

Masz teraz kompletną automatyzację Inkscape przez CLI/API! 🚀
