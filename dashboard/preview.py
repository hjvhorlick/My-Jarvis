"""dashboard/preview.py — browser preview harness for the JARVIS dashboard.

Runs the real dashboard (same FastAPI app, same WebSocket, same UI in
`static/`) without the PyQt desktop app behind it, so the interface can be
opened in an ordinary browser.

What it does differently from `server.serve()`:

  * binds straight to 0.0.0.0 with a plain uvicorn config — no firewall /
    UAC / TLS-cert plumbing, which is desktop-only behaviour
  * "/" is replaced with a landing route that hands out a session token
    automatically, so there is no PIN to type
  * a small simulator drains `_command_queue` and answers with demo text
    instead of forwarding commands to Gemini Live

Run it with:

    python -m dashboard.preview            # http://0.0.0.0:8000
    JARVIS_PREVIEW_PORT=8000 python -m dashboard.preview

Requires: pip install fastapi "uvicorn[standard]" cryptography python-multipart
"""

from __future__ import annotations

import asyncio
import os
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dashboard.server import DashboardServer  # noqa: E402

try:
    from fastapi.responses import HTMLResponse  # noqa: E402
    import uvicorn  # noqa: E402
except ImportError:  # pragma: no cover
    print("[Preview] fastapi/uvicorn missing — run:")
    print("[Preview]   pip install fastapi 'uvicorn[standard]' cryptography python-multipart")
    raise SystemExit(1)


PORT = int(os.environ.get("JARVIS_PREVIEW_PORT", "8000"))

# ── demo conversation ─────────────────────────────────────────────────────────

_WELCOME = [
    {"type": "sys", "text": "Preview mode — no desktop app or Gemini key attached."},
    {"type": "log", "speaker": "jarvis",
     "text": "Systems online. This is the dashboard preview: commands are answered "
             "by a local stand-in, so nothing reaches your PC or the Gemini API."},
    {"type": "sys", "text": "Try: \"what's the weather\", \"play some music\", \"status report\"."},
]

_REPLIES = [
    (("weather", "rain", "temperature", "forecast"),
     "It is 24°C and clear in Benoni right now — light breeze from the north-east, "
     "no rain expected until Thursday evening."),
    (("play", "music", "song", "spotify"),
     "Queuing your focus playlist. Tell me when you want it louder."),
    (("status", "report", "systems", "health"),
     "All systems nominal: voice pipeline idle, memory store loaded, "
     "four actions registered, zero background errors in the last hour."),
    (("time", "clock", "date"),
     "It is a quarter past ten on Saturday morning."),
    (("file", "upload", "send"),
     "Files you attach here land in the uploads folder and show up as cards "
     "in this feed — try the paperclip."),
    (("hello", "hi", "hey", "jarvis"),
     "At your service. What would you like me to look at?"),
    (("who are you", "what are you", "your name"),
     "JARVIS V1 — Vincent's personal assistant, running a Gemini Live voice core, "
     "with this dashboard as the remote control surface."),
]

_FALLBACK = (
    "Understood. In the real app that would be routed to Gemini Live and acted on; "
    "here I only echo the intent back so you can see the interface work."
)


def _reply_for(text: str) -> str:
    low = text.lower()
    for needles, reply in _REPLIES:
        if any(n in low for n in needles):
            return reply
    return _FALLBACK


# ── preview server ───────────────────────────────────────────────────────────


def _landing_html(token: str, key: str, port: int) -> str:
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>JARVIS — Preview</title>
<style>
  html,body{{height:100%;margin:0;background:#07090f;color:#dde3ed;
    font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
    display:flex;align-items:center;justify-content:center;text-align:center}}
  .wrap{{padding:32px}}
  .logo{{font-size:20px;font-weight:700;letter-spacing:10px;margin-bottom:18px}}
  .logo em{{color:#6366f1;font-style:normal}}
  p{{color:#5e6a7e;font-size:13px;line-height:1.7;margin:0}}
  .bar{{width:180px;height:3px;margin:22px auto 0;border-radius:2px;
    background:rgba(255,255,255,0.07);overflow:hidden}}
  .bar span{{display:block;height:100%;width:40%;background:#6366f1;border-radius:2px;
    animation:slide 1s ease-in-out infinite}}
  @keyframes slide{{0%{{margin-left:-40%}}100%{{margin-left:100%}}}}
</style></head>
<body><div class="wrap">
  <div class="logo"><em>J</em>ARVIS</div>
  <p>Opening dashboard preview…</p>
  <div class="bar"><span></span></div>
</div>
<script>
  setTimeout(function () {{ location.replace('/?t={token}&k={key}'); }}, 250);
</script>
</body></html>"""


def build_preview() -> DashboardServer:
    server = DashboardServer()

    # Desktop-only side effects: wake callback just flips the status pill.
    server.set_wake_callback(
        lambda: asyncio.create_task(server.broadcast({"type": "status", "state": "active"}))
    )
    server.set_connect_callback(
        lambda: asyncio.create_task(server.broadcast({"type": "status", "state": "active"}))
    )

    app = server.app

    # Replace "/" (index) with the auto-login landing page.
    app.router.routes = [r for r in app.router.routes if getattr(r, "path", None) != "/"]

    @app.get("/", response_class=HTMLResponse)
    async def preview_index(t: str = "", k: str = ""):
        """Auto-login: mint a session, then hand the UI its token inline.

        The token is inlined into the page instead of being stashed in
        sessionStorage, so the preview works inside an embedded frame where
        storage may be partitioned or blocked.
        """
        if t and t in server._tokens:
            key = server._token_keys.get(t, "")
            html = (server._app_html
                    .replace("__IP__", server._ip)
                    .replace("__PORT__", str(PORT))
                    .replace("sessionStorage.getItem('jarvis_token')", repr(t))
                    .replace("sessionStorage.getItem('jarvis_key')", repr(key)))
            return HTMLResponse(html)

        token = secrets.token_urlsafe(32)
        key = "".join(secrets.choice("ABCDEFGHJKMNPQRSTUVWXYZ23456789") for _ in range(6))
        server._tokens.add(token)
        server._token_keys[token] = key
        server._aes_key(key)
        return HTMLResponse(_landing_html(token, key, PORT))

    @app.get("/healthz")
    async def healthz():  # noqa: ANN202
        return {"ok": True, "mode": "preview", "clients": len(server._clients)}

    return server


async def _seed(server: DashboardServer) -> None:
    await server.broadcast({"type": "status", "state": "active"})
    for msg in _WELCOME:
        await server.broadcast(msg)


async def _simulator(server: DashboardServer) -> None:
    """Drain commands and answer with demo text."""
    while True:
        text = await server._command_queue.get()
        await asyncio.sleep(0.45)
        await server.broadcast({"type": "status", "state": "active"})
        await server.broadcast({"type": "log", "speaker": "jarvis", "text": _reply_for(text)})


async def _main() -> None:
    server = build_preview()
    await _seed(server)
    asyncio.create_task(_simulator(server))

    print(f"[Preview] dashboard UI  ->  http://0.0.0.0:{PORT}/")
    print("[Preview] demo mode: canned replies, no desktop app, no Gemini calls.")
    cfg = uvicorn.Config(server.app, host="0.0.0.0", port=PORT, log_level="warning")
    await uvicorn.Server(cfg).serve()


if __name__ == "__main__":
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        pass
