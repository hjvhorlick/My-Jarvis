# JARVIS — Vincent's personal assistant

Voice assistant running on Gemini Live. Personal use only.

## Run
    ~/Jarvis/run.sh          # or double-click the desktop icon

## Preview the dashboard in a browser
The remote dashboard (`dashboard/server.py` + `dashboard/static/`) can be opened in a
plain browser without the desktop app or a Gemini key:

    ./preview.sh                           # http://0.0.0.0:8000

`preview.sh` keeps the extra deps (fastapi, uvicorn, cryptography,
python-multipart) in `~/.jarvis-preview-venv` and reinstalls them automatically if
they are missing, so it repairs a fresh checkout by itself. Raw equivalent:

    python -m dashboard.preview            # needs those deps installed

Preview mode binds straight to `0.0.0.0`, logs you in automatically (no PIN), and
answers commands with canned demo text — the real UI, WebSocket feed, encryption
badge and file uploads all work; nothing is forwarded to your PC or to Gemini.

## Settings
⚙ in the app → voice (30 Gemini voices), speaking style, wake word, audio devices.
Config lives in `config/api_keys.json`. Personality in `core/prompt.txt`.

## My changes
- Voice upgrade: all 30 Gemini voices, speaking-style presets, in-app preview
- Rebranded as JARVIS V1

See CREDITS.md for origin and licence.
