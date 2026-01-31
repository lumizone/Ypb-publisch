# Instalacja Cairo dla macOS

Jeśli widzisz błędy związane z Cairo (np. "no library called cairo-2 was found"), musisz zainstalować bibliotekę Cairo systemową.

## macOS z Homebrew

```bash
brew install cairo pkg-config
```

Następnie upewnij się, że Python widzi biblioteki:

```bash
# Dla Homebrew na Apple Silicon (M1/M2/M3)
export PKG_CONFIG_PATH="/opt/homebrew/lib/pkgconfig:$PKG_CONFIG_PATH"
export DYLD_LIBRARY_PATH="/opt/homebrew/lib:$DYLD_LIBRARY_PATH"

# Dla Homebrew na Intel
export PKG_CONFIG_PATH="/usr/local/lib/pkgconfig:$PKG_CONFIG_PATH"
export DYLD_LIBRARY_PATH="/usr/local/lib:$DYLD_LIBRARY_PATH"
```

## Alternatywnie: Użyj metody obrazowej

Jeśli nie chcesz instalować Cairo, generator automatycznie użyje metody obrazowej (PNG template) jako fallback, która działa bez Cairo.

## Weryfikacja

Po instalacji Cairo, sprawdź czy działa:

```bash
python -c "from cairosvg import svg2png; print('Cairo działa!')"
```

Jeśli widzisz błąd, sprawdź czy biblioteki są w PATH:

```bash
brew list cairo
pkg-config --libs cairo
```
