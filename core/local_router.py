"""Fast local handling for common, deterministic JARVIS requests.

This module deliberately does not call an LLM. It handles requests whose
meaning and result are available on the machine: the current date/time, opening
mail or a website, launching a known application, and opening a named document.
Unmatched requests return ``None`` so the caller can forward them to Gemini.
"""
from __future__ import annotations

import os
import re
import subprocess
import webbrowser
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse


@dataclass(frozen=True)
class LocalResult:
    """Result of a locally understood request."""
    text: str
    handled: bool = True


_MAIL_URLS = {
    "gmail": "https://mail.google.com/",
    "google mail": "https://mail.google.com/",
    "outlook": "https://outlook.live.com/mail/",
    "outlook mail": "https://outlook.live.com/mail/",
    "yahoo mail": "https://mail.yahoo.com/",
    "proton mail": "https://mail.proton.me/",
}

_SITE_URLS = {
    "google": "https://www.google.com/",
    "youtube": "https://www.youtube.com/",
    "wikipedia": "https://www.wikipedia.org/",
    "facebook": "https://www.facebook.com/",
    "instagram": "https://www.instagram.com/",
    "reddit": "https://www.reddit.com/",
    "netflix": "https://www.netflix.com/",
    "amazon": "https://www.amazon.com/",
    "bbc": "https://www.bbc.com/",
    "bbc news": "https://www.bbc.com/news",
    "google drive": "https://drive.google.com/",
    "google docs": "https://docs.google.com/",
    "google calendar": "https://calendar.google.com/",
}

_DOC_EXTENSIONS = {
    ".doc", ".docx", ".odt", ".rtf", ".pdf", ".txt", ".md",
    ".xls", ".xlsx", ".ods", ".csv", ".ppt", ".pptx", ".odp",
}
_MAX_FILE_CANDIDATES = 1200


def _clean(text: str) -> str:
    text = (text or "").strip().lower()
    text = re.sub(r"[.!?,;:]+$", "", text)
    text = re.sub(r"\s+", " ", text)
    return text


def _open_url(url: str) -> bool:
    """Ask the system's default browser to open a URL without waiting for it."""
    try:
        return bool(webbrowser.open(url, new=2))
    except Exception as exc:
        print(f"[LocalRouter] Browser launch failed: {exc}")
        return False


def _extract_target(text: str, verbs: tuple[str, ...]) -> str | None:
    for verb in verbs:
        match = re.match(rf"^{re.escape(verb)}\s+(.+)$", text)
        if match:
            target = match.group(1).strip()
            target = re.sub(r"^(?:the|my)\s+", "", target)
            target = re.sub(r"\s+(?:please|for me)$", "", target)
            return target.strip(" \"'")
    return None


def _website_url(target: str) -> str | None:
    target = target.strip().strip(" \"'")
    if not target:
        return None
    lower = target.lower()
    if lower in _SITE_URLS:
        return _SITE_URLS[lower]
    if lower.startswith(("http://", "https://")):
        return target
    if lower.startswith("www."):
        return "https://" + target
    # Accept explicit domains, not arbitrary words that might be an app name.
    if re.fullmatch(r"(?:[a-z0-9-]+\.)+[a-z]{2,}(?:/[\w./?%&=+#~:-]*)?", lower):
        return "https://" + target
    return None


def _launch_file(path: Path) -> bool:
    try:
        if os.name == "nt":
            os.startfile(str(path))  # type: ignore[attr-defined]
        elif sys_platform() == "Darwin":
            subprocess.Popen(["open", str(path)], stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
        else:
            subprocess.Popen(["xdg-open", str(path)], stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
        return True
    except Exception as exc:
        print(f"[LocalRouter] Could not open {path}: {exc}")
        return False


def sys_platform() -> str:
    # Keep platform lookup lazy and easy to override in tests.
    import platform
    return platform.system()


def _document_roots() -> list[Path]:
    home = Path.home()
    roots = [home / name for name in ("Documents", "Desktop", "Downloads")]
    return [p for p in roots if p.is_dir()]


def _find_document(query: str) -> tuple[list[Path], bool]:
    """Find a document by explicit path or a bounded shallow search.

    Returns (matches, search_was_limited). It does not crawl the whole home
    directory or open a fuzzy near-match on the user's behalf.
    """
    raw = Path(query).expanduser()
    if raw.is_file():
        return [raw], False

    # A bare filename can be relative to the current working directory.
    if raw.is_absolute() and raw.exists():
        return ([raw] if raw.is_file() else []), False

    wanted = query.strip().strip(" \"'")
    wanted_path = Path(wanted).expanduser()
    if wanted_path.is_file():
        return [wanted_path], False
    wanted_name = wanted_path.name.lower()
    wanted_stem = Path(wanted_name).stem
    wanted_stem = re.sub(r"[^a-z0-9]+", " ", wanted_stem).strip()
    if not wanted_stem:
        return [], False

    exact: list[Path] = []
    partial: list[Path] = []
    visited = 0
    limited = False
    for root in _document_roots():
        # Search only two directory levels deep to keep a voice command quick.
        try:
            for current, dirs, files in os.walk(root):
                rel = Path(current).relative_to(root)
                depth = len(rel.parts)
                if depth >= 2:
                    dirs[:] = []
                else:
                    dirs[:] = [d for d in dirs if not d.startswith(".")]
                for filename in files:
                    visited += 1
                    if visited > _MAX_FILE_CANDIDATES:
                        limited = True
                        break
                    path = Path(current) / filename
                    if path.suffix.lower() not in _DOC_EXTENSIONS:
                        continue
                    name_lower = filename.lower()
                    stem = re.sub(r"[^a-z0-9]+", " ", path.stem.lower()).strip()
                    if name_lower == wanted_name or stem == wanted_stem:
                        exact.append(path)
                    elif wanted_stem in stem:
                        partial.append(path)
                if limited:
                    break
        except OSError:
            continue
        if limited:
            break

    return (exact or partial), limited


def _document_request(text: str) -> str | None:
    # Explicit file extensions are unambiguous, including "open budget.xlsx".
    match = re.match(
        r"^(?:please\s+)?(?:open|show|read)\s+(?:the\s+)?(.+?\.(?:docx?|odt|rtf|pdf|txt|md|xlsx?|ods|csv|pptx?|odp))(?:\s+please)?$",
        text,
    )
    if match:
        return match.group(1).strip(" \"'")

    match = re.match(
        r"^(?:please\s+)?(?:open|show|read)\s+(?:my\s+)?(?:document|file|spreadsheet|presentation)\s+(?:called\s+|named\s+)?(.+)$",
        text,
    )
    if match:
        return match.group(1).strip(" \"'")

    match = re.match(
        r"^(?:please\s+)?(?:open|show|read)\s+(?:my\s+)?(?:document|file|spreadsheet|presentation)$",
        text,
    )
    if match:
        return ""

    return None


def _open_document(query: str) -> LocalResult:
    if not query:
        return LocalResult("Which document should I open?")
    matches, limited = _find_document(query)
    if not matches:
        suffix = " I checked your Documents, Desktop, and Downloads folders." if not limited else " I checked the first part of your Documents, Desktop, and Downloads folders."
        return LocalResult(f"I couldn't find '{query}'.{suffix} Give me the exact file name or path.")
    if len(matches) > 1:
        names = ", ".join(p.name for p in matches[:5])
        return LocalResult(f"I found a few matches: {names}. Which one should I open?")
    path = matches[0]
    if _launch_file(path):
        return LocalResult(f"Opening {path.name}.")
    return LocalResult(f"I found {path.name}, but couldn't open it with your system's file handler.")


def handle_local_request(text: str) -> LocalResult | None:
    """Handle a recognized everyday request without Gemini.

    Return ``None`` only if this router has no confident match, so the caller
    may use Gemini for the request. A recognized but unsuccessful operation
    still returns a local, honest response rather than silently falling back.
    """
    raw = (text or "").strip()
    raw = re.sub(r"^(?:hey\s+)?jarvis[\s,.:!-]+", "", raw, flags=re.IGNORECASE)
    value = _clean(raw)
    if not value:
        return None

    # Date/time are deterministic and always use the machine's current timezone.
    if re.fullmatch(
        r"(?:time|current time|time now|what time(?: is it)?(?: now)?|"
        r"what(?:'s| is) the time(?: now)?|tell me the time)",
        value,
    ):
        now = datetime.now().astimezone()
        clock = now.strftime("%I:%M %p").lstrip("0")
        return LocalResult(f"It's {clock}.")
    if value in {
        "date", "what is the date", "what's the date", "what date is it",
        "what day is it", "what day is today", "what is today's date",
        "what's today's date", "today's date",
    }:
        now = datetime.now().astimezone()
        day = now.strftime("%d").lstrip("0")
        return LocalResult(f"It's {now.strftime('%A, %B')} {day}.")

    # Mail request: opening the inbox is local; reading message contents is not
    # claimed unless a separate mail connector is actually configured.
    mail_target = None
    if re.fullmatch(r"(?:open|check|show|go to)\s+(?:(?:my|the)\s+)?(?:email|emails|mail|inbox)", value):
        mail_target = "gmail"
    else:
        mail_target = _extract_target(value, ("open", "check", "show", "go to"))
        if mail_target and mail_target not in _MAIL_URLS:
            mail_target = None
    if mail_target in _MAIL_URLS:
        url = _MAIL_URLS[mail_target]
        label = {"gmail": "Gmail", "google mail": "Gmail", "outlook": "Outlook", "outlook mail": "Outlook", "yahoo mail": "Yahoo Mail", "proton mail": "Proton Mail"}[mail_target]
        if _open_url(url):
            return LocalResult(f"Opening {label}.")
        return LocalResult(f"I couldn't open {label}; there isn't a working default browser.")

    # A document operation should never be interpreted as a web domain.
    document = _document_request(value)
    if document is not None:
        return _open_document(document)

    # Open a web page directly in the system's existing default browser.
    site_target = _extract_target(value, ("open", "go to", "visit", "browse to"))
    if site_target:
        url = _website_url(site_target)
        if url:
            host = urlparse(url).hostname or site_target
            if _open_url(url):
                return LocalResult(f"Opening {host}.")
            return LocalResult(f"I couldn't open {host}; there isn't a working default browser.")

    # Launch a known installed app by an exact alias. Unknown app names are left
    # to Gemini rather than letting substring matching open the wrong program.
    app_target = _extract_target(value, ("open", "launch", "start"))
    if app_target:
        try:
            from actions.open_app import _APP_ALIASES, open_app
            if app_target in _APP_ALIASES:
                result = open_app({"app_name": app_target})
                return LocalResult(result)
        except Exception as exc:
            return LocalResult(f"I couldn't open {app_target}: {exc}")

    return None
