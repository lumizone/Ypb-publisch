#!/bin/bash
# Script do zatrzymania aplikacji

pkill -9 -f "python.*app.py" && echo "✓ Aplikacja zatrzymana" || echo "Aplikacja nie była uruchomiona"
