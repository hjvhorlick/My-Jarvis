"""
barehands — hand-tracked glass board for JARVIS  (drop-in plugin)

Gives JARVIS:
  • a voice tool:  "open barehands" / "show me X on the board" / "clear the board" / "close barehands"
  • a settings panel (⚙ → PLUGIN SETTINGS → BAREHANDS): start/stop button, auto-start toggle, port, browser
  • a live ring: JARVIS's LISTENING / THINKING / SPEAKING state is mirrored into barehands/state/

barehands itself: https://github.com/jaredrhod/barehands  (AGPL-3.0). It runs as its own local
web server; the browser page does the hand tracking with your webcam. Nothing leaves the machine.
"""
from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

# ── where barehands lives ──────────────────────────────────────────────────────
_HERE     = Path(__file__).resolve().parent            # plugins/
_ROOT     = _HERE.parent                               # ~/Jarvis
_BH_DIR   = _ROOT / "barehands"                        # ~/Jarvis/barehands  (cloned by installer)
_STATE    = _BH_DIR / "state"
_NS       = "barehands"
_PROC: subprocess.Popen | None = None
_LOCK     = threading.Lock()


def _cfg(key, default=None):
    try:
        from memory.config_manager import get_plugin_setting
        v = get_plugin_setting(_NS, key, default)
        return default if v in (None, "") else v
    except Exception:
        return default


def _port() -> int:
    try:
        return int(_cfg("port", 8794))
    except Exception:
        return 8794


def _url(role: str = "") -> str:
    return f"http://127.0.0.1:{_port()}/stage.html" + (f"?role={role}" if role else "")


def _alive() -> bool:
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{_port()}/config", timeout=0.6).read()
        return True
    except Exception:
        return False


def _sync_config():
    """Keep barehands.json in step with our settings (name + port)."""
    try:
        from memory.config_manager import get_assistant_name
        name = get_assistant_name()
    except Exception:
        name = "JARVIS"
    p = _BH_DIR / "barehands.json"
    try:
        data = json.loads(p.read_text()) if p.exists() else {}
    except Exception:
        data = {}
    data["name"] = name
    data["port"] = _port()
    data.setdefault("orbs", [
        {"title": "Notes", "path": "sample-notes", "kind": "notes"},
        {"title": "Props", "path": "media", "kind": "media"},
    ])
    p.write_text(json.dumps(data, indent=2))


def _open_browser(role: str = ""):
    url = _url(role)
    pref = str(_cfg("browser", "default")).lower()
    _known = {
        "opera":  ["opera", "opera-stable", "opera-beta", "opera-developer"],
        "chrome": ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser"],
        "brave":  ["brave-browser", "brave"],
    }
    # "default": use whichever Chromium-family browser is installed (Opera first),
    # falling back to the system default only if none is found.
    cands = _known.get(pref) or (_known["opera"] + _known["chrome"] + _known["brave"])
    for cand in cands:
        exe = shutil.which(cand)
        if exe:
            subprocess.Popen([exe, f"--app={url}"] if _cfg("app_window", True) else [exe, url],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
    webbrowser.open(url)


def start(open_page: bool = True) -> tuple[bool, str]:
    global _PROC
    with _LOCK:
        if not (_BH_DIR / "server.py").exists():
            return False, f"barehands is not installed at {_BH_DIR}. Run the installer script."
        _sync_config()
        if not _alive():
            _PROC = subprocess.Popen(
                [sys.executable, "server.py"], cwd=str(_BH_DIR),
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True)
            for _ in range(40):                      # up to ~4 s
                if _alive():
                    break
                time.sleep(0.1)
            if not _alive():
                return False, "the barehands server did not come up — check the port in settings."
        _STATE.mkdir(exist_ok=True)
        (_STATE / "state").write_text("listening")
        if open_page:
            _open_browser()
        return True, f"barehands is up at {_url()}"


def stop() -> tuple[bool, str]:
    global _PROC
    with _LOCK:
        try:
            (_STATE / "state").write_text("idle")
        except Exception:
            pass
        if _PROC and _PROC.poll() is None:
            try:
                os.killpg(os.getpgid(_PROC.pid), signal.SIGTERM)
            except Exception:
                _PROC.terminate()
            _PROC = None
            return True, "barehands stopped."
        if _alive():
            return False, "barehands is running but was not started by me — close its terminal to stop it."
        return True, "barehands was not running."


def _cmd(payload: dict) -> tuple[bool, str]:
    """POST a board command (server enforces its own allowlist)."""
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{_port()}/cmd",
            data=json.dumps(payload).encode(), method="POST",
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=2) as r:
            return True, r.read().decode()[:200]
    except Exception as e:
        return False, str(e)


def board_state() -> str:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{_port()}/state", timeout=2) as r:
            data = json.loads(r.read().decode() or "{}")
        items = data.get("items") or data.get("cards") or data
        return json.dumps(items)[:1500]
    except Exception as e:
        return f"(could not read board: {e})"


# ── live ring: mirror JARVIS state into barehands/state/state ─────────────────
_STATE_MAP = {"LISTENING": "listening", "THINKING": "thinking", "SPEAKING": "speaking",
              "SLEEPING": "idle", "IDLE": "idle"}
_hooked = False


def _hook_state(player):
    """Wrap player.set_state once so every state change also lands in the board's ring."""
    global _hooked
    if _hooked or player is None or not hasattr(player, "set_state"):
        return
    orig = player.set_state

    def wrapped(state, *a, **k):
        try:
            if _STATE.exists():
                (_STATE / "state").write_text(_STATE_MAP.get(str(state).upper(), "idle"))
        except Exception:
            pass
        return orig(state, *a, **k)

    try:
        player.set_state = wrapped
        _hooked = True
    except Exception:
        pass


# ── the voice tool ─────────────────────────────────────────────────────────────
PLUGIN = {
    "name": "barehands",
    "description": (
        "Control the barehands hand-tracked glass board (a browser window the user moves with "
        "their bare hands via webcam). Use action 'open' when the user says open/start/launch "
        "barehands, the board, the glass, hand tracking, or 'let me use my hands'. Use 'close' to "
        "stop it. When the user asks to SEE something — 'show me', 'put it up', 'put that on the "
        "board/glass' — use 'present' with a title and short body instead of reading a long answer "
        "aloud. Use 'card' to add a smaller note card, 'clear' to wipe the board, 'status' to ask "
        "whether it is running and what is on it. Gestures for the user: raise a hand for a cursor, PINCH thumb+index to grab/move a card, open hand to release. Not for screenshots or webcam vision — that is "
        "screen_process."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING",
                       "description": "one of: open, close, present, card, clear, status"},
            "title":  {"type": "STRING", "description": "heading for present/card (short, UPPERCASE ok)"},
            "body":   {"type": "STRING", "description": "text for present/card — keep under 60 words"},
        },
        "required": ["action"],
    },
}


def run(parameters: dict, player=None, session_memory=None) -> str:
    _hook_state(player)
    action = str(parameters.get("action", "")).strip().lower()
    title  = str(parameters.get("title", "") or "").strip()
    body   = str(parameters.get("body", "") or "").strip()

    def log(t):
        if player:
            try:
                player.write_log(f"BAREHANDS: {t}")
            except Exception:
                pass
    try:
        if action in ("open", "start", "launch", "on"):
            ok, msg = start(open_page=True)
            log(msg)
            return ("The board is up, sir. Allow the camera when the browser asks, and raise a hand."
                    if ok else f"I couldn't start barehands: {msg}")

        if action in ("close", "stop", "off"):
            ok, msg = stop(); log(msg)
            return "Board closed." if ok else msg

        if action == "status":
            if not _alive():
                return "barehands is not running. Say 'open barehands' to start it."
            return f"barehands is running. On the board right now: {board_state()}"

        if action in ("present", "card", "clear"):
            if not _alive():
                ok, msg = start(open_page=True); log(msg)
                if not ok:
                    return f"I couldn't start the board: {msg}"
                time.sleep(1.5)
            if action == "clear":
                ok, msg = _cmd({"a": "clear"}); return "Board cleared." if ok else f"Clear failed: {msg}"
            payload = {"a": "present" if action == "present" else "add_card",
                       "title": title or "NOTE", "body": body}
            ok, msg = _cmd(payload); log(f"{payload['a']} → {title}")
            return (f"It's on the glass: {title or 'note'}." if ok else f"Board command failed: {msg}")

        return "Barehands actions are: open, close, present, card, clear, status."
    except Exception as e:
        return f"Sir, the barehands plugin failed: {e}"


# ── settings panel (⚙ → PLUGIN SETTINGS) ───────────────────────────────────────
def _toggle_action(values: dict):
    """The one button: starts if stopped, stops if running. Returns (ok, message)."""
    if _alive():
        return stop()
    ok, msg = start(open_page=True)
    return ok, (msg + "  — browser opening…") if ok else msg


PLUGIN_SETTINGS = {
    "namespace": _NS,
    "title": "BAREHANDS — hand-tracked board",
    "fields": [
        {"key": "autostart",  "type": "toggle", "label": "Start barehands with JARVIS", "default": False},
        {"key": "app_window", "type": "toggle", "label": "Open as its own window (no tabs)", "default": True},
        {"key": "browser",    "type": "choice", "label": "Browser",
         "options": ["opera", "default", "chrome", "brave"], "default": "opera"},
        {"key": "port",       "type": "text",   "label": "Port", "default": "8794"},
    ],
    "action": {"label": "▶ / ■  START · STOP BAREHANDS", "run": _toggle_action},
}


# ── auto-start ────────────────────────────────────────────────────────────────
def _autostart():
    time.sleep(6)                                   # let JARVIS finish booting
    try:
        if str(_cfg("autostart", False)).lower() in ("1", "true", "yes", "on"):
            start(open_page=True)
    except Exception:
        pass


threading.Thread(target=_autostart, daemon=True).start()

