# Super AI Agent

The existing Gemini Live voice and personality is **JARVIS**. The new Tauri interface is branded **Super AI Agent** and is still a disconnected visual preview; the existing voice agent has not been changed or replaced. The JARVIS build remains personal and non-commercial, as detailed in `CREDITS.md`.

## Run
    ~/Jarvis/run.sh          # or double-click the desktop icon

## Web UI / remote control
A browser-based dashboard is already included. Start JARVIS as usual, open **Remote Control** in the desktop app, then scan the QR code or open the displayed address and enter the one-time session key. A phone and the JARVIS computer should be on the same local network.

The dashboard supports sending commands, viewing the live conversation, waking JARVIS, using your phone microphone, and transferring files. Keep the desktop app running while using it. This is a companion remote UI, not a full replacement for the desktop settings interface; don't expose its port to the public internet.

The dashboard starts automatically when its dependencies are installed (`fastapi`, `uvicorn`, and `cryptography`, included in `requirements.txt`).

## Tauri desktop UI preview
A separate, Tauri-compatible UI prototype is in `desktop-ui/`. **Super AI Agent** is the app brand and **JARVIS** is shown as its current voice/personality character. The existing Python voice agent and PyQt app remain unchanged and disconnected. My Hands now has a separate, optional local tracking service; it only receives video frames after the user explicitly enables the camera and does not open or route audio. See `desktop-ui/README.md` for the preview and service steps.

Native Tauri builds require Rust/Cargo. The production sidecar packaging and native camera permission/IPC configuration are still pending.

## Settings
⚙ in the app → voice (30 Gemini voices), speaking style, wake word, audio devices.
Config lives in `config/api_keys.json`. Personality in `core/prompt.txt`.

## My changes
- Voice upgrade: all 30 Gemini voices, speaking-style presets, in-app preview
- Rebranded as JARVIS V1

See CREDITS.md for origin and licence.
