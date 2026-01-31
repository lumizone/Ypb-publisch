# Jak uruchomić aplikację

## Sposób 1: Użyj skryptu start.sh (najprostszy)

```bash
cd /Users/lukasz/YPBv2
./start.sh
```

## Sposób 2: Ręczne uruchomienie

```bash
cd /Users/lukasz/YPBv2
source .venv/bin/activate
source setup_env.sh
python app.py
```

## Sposób 3: Użyj run.sh

```bash
cd /Users/lukasz/YPBv2
./run.sh app.py
```

## Po uruchomieniu

Aplikacja będzie dostępna pod adresem:
- **http://localhost:8000**

Otwórz ten adres w przeglądarce.

## Zatrzymanie aplikacji

Naciśnij `Ctrl+C` w terminalu, gdzie działa aplikacja.

## Rozwiązywanie problemów

Jeśli widzisz błąd związany z Cairo:
```bash
brew install cairo pkg-config
```

Następnie uruchom ponownie aplikację.
