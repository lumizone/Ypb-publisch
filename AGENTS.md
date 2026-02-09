# AGENTS.md

## Scope
This file defines practical instructions for coding agents working in this repository.

## Project
- Stack: Python Flask app for label + mockup generation.
- Main app entry: `app.py`.
- Frontend template: `app_dashboard.html`.
- Fallback text parsing/replacement: `template_parser.py`, `text_replacer.py`, `text_formatter.py`.

## Local Run
- App port: `8000` (default in `app.py`).
- URL: `http://localhost:8000`.
- Do not assume port `5000`.

## Server Start (Stable)
Use this when normal background start dies unexpectedly in this environment.

- Start (foreground, stable):
`cd /Users/lukasz/YPBv2 && export PYTHONUNBUFFERED=1 PORT=8000 && .venv/bin/python app.py`

- Start with log file mirror:
`cd /Users/lukasz/YPBv2 && export PYTHONUNBUFFERED=1 PORT=8000 && .venv/bin/python app.py 2>&1 | tee -a /tmp/flask_app.log`

- Verify:
`curl -sS -m 5 -o /tmp/ypb_health.html -w "%{http_code}\n" http://127.0.0.1:8000/`

- Check listener:
`lsof -nP -iTCP:8000 -sTCP:LISTEN`

## Legacy Scripts
- `./start.sh`, `./restart.sh`, `./stop.sh` exist and may work locally.
- If `restart.sh` starts and process exits immediately, use the stable foreground mode above.

## Logs
- Primary runtime log path: `/tmp/flask_app.log`.
- For live diagnosis, tail logs while reproducing issue:
`tail -f /tmp/flask_app.log`

## Current Fallback Notes
- Fallback triggers when AI/SVG text extraction is garbled (`�` chars).
- Position-based parsing tags primary and secondary text nodes.
- Replacer removes secondary nodes to avoid mixed old/new text in one area.
- SKU auto-selection tries to avoid disclaimer lines like `FOR IM OR SQ USE ONLY`.

## Editing Rules
- Keep changes minimal and targeted.
- Do not revert unrelated user changes.
- Validate behavior on the real fallback flow after touching:
`template_parser.py`, `text_replacer.py`, `app.py`, `app_dashboard.html`.

## Quick Recovery Checklist
- Confirm server process exists.
- Confirm `:8000` listener exists.
- Confirm HTTP `200` on `http://127.0.0.1:8000/`.
- If not, restart in stable foreground mode and collect `/tmp/flask_app.log`.
