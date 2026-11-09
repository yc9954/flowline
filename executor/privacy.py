"""Privacy filter shared by the observer and the compiler.

* `mask_title` masks personal names (names list + Title Case bigrams) → "[name]".
* `classify_private` flags chat / banking windows from app + title keywords.
"""
from __future__ import annotations

import hashlib
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))

CHAT_KEYWORDS = ("personal chat", "chat ·", "whatsapp", "telegram", "signal", "imessage", "messages", "kakaotalk",
                 "discord", "messenger", "line ·")
BANK_KEYWORDS = ("bank", "banking", "chase", "wells fargo", "citi", "capital one", "paypal", "venmo", "brokerage")
CHAT_APPS = ("xmessage", "zenity", "telegram", "signal", "discord", "whatsapp", "slack", "kakaotalk")

# Words that look like Title Case names but are not.
ALLOW_WORDS = {
    "LibreOffice", "Calc", "Impress", "Writer", "Draw", "Math", "Base", "Untitled", "Document", "Desktop", "Personal",
    "Chat", "First", "National", "Bank", "Login", "Mozilla", "Firefox", "Chromium", "Google", "Chrome", "New", "Tab",
    "Select", "Template", "Save", "Open", "File", "Applications", "Terminal", "Settings", "Mail", "Inbox", "Proposal",
    "Pricing", "Sheet", "Deck", "Halden", "Logistics", "Northwind", "Fitness", "Investment", "Review", "Contract",
    "Staff", "Seats", "Total", "Items", "Amount", "Slide", "Page", "Web", "Store", "Home", "Edit", "View", "Help",
}


def load_names(path: str | None = None) -> list[str]:
    p = path or os.path.join(HERE, "names.txt")
    if not os.path.exists(p):
        return []
    with open(p, encoding="utf-8") as f:
        return [l.strip() for l in f if l.strip() and not l.startswith("#")]


_NAMES = None


def names() -> list[str]:
    global _NAMES
    if _NAMES is None:
        _NAMES = load_names()
    return _NAMES


_BIGRAM = re.compile(r"\b([A-Z][a-z]{1,})\s+([A-Z][a-z]{1,})\b")


def mask_title(title: str, name_list: list[str] | None = None) -> str:
    out = title
    for n in sorted(name_list if name_list is not None else names(), key=len, reverse=True):
        out = re.sub(r"\b" + re.escape(n) + r"\b", "[name]", out, flags=re.IGNORECASE)

    def repl(m):
        a, b = m.group(1), m.group(2)
        if a in ALLOW_WORDS or b in ALLOW_WORDS:
            return m.group(0)
        return "[name]"

    out = _BIGRAM.sub(repl, out)
    out = re.sub(r"(\[name\]\s*)+", "[name] ", out).strip()
    return out


def title_hash(title: str) -> str:
    return hashlib.sha256(title.encode("utf-8")).hexdigest()


def app_from_wm_class(wm_class: str) -> str:
    """'"libreoffice", "libreoffice-calc"' → 'libreoffice-calc'; 'Xmessage' → 'xmessage'."""
    parts = [p.strip().strip('"') for p in wm_class.split(",") if p.strip()]
    if not parts:
        return "unknown"
    return parts[-1].lower()


def app_label(app: str, title: str = "") -> str:
    """Short, non-identifying app name used in Events."""
    a = app.lower()
    if "calc" in a:
        return "calc"
    if "impress" in a:
        return "impress"
    if "writer" in a:
        return "writer"
    if "libreoffice" in a or "soffice" in a:
        t = title.lower()
        for k in ("calc", "impress", "writer"):
            if k in t:
                return k
        return "libreoffice"
    if any(k in a for k in ("chromium", "chrome", "firefox")):
        return "browser"
    if a in ("xfdesktop", "desktop", "xfce4-panel"):
        return "desktop"
    return a or "unknown"


def classify_private(app: str, title: str) -> str | None:
    """→ 'personal_chat' | 'banking' | None."""
    t = title.lower()
    a = app.lower()
    if any(k in t for k in CHAT_KEYWORDS) or any(k in a for k in CHAT_APPS):
        return "personal_chat"
    if any(k in t for k in BANK_KEYWORDS):
        return "banking"
    return None


_FILE_RE = re.compile(r"([^/\\—–|:]+?\.(?:ods|odp|odt|xlsx|pptx|docx|pdf|csv|txt|md))\b", re.IGNORECASE)


def file_hint(title: str) -> str | None:
    m = _FILE_RE.search(title)
    if not m:
        return None
    return mask_title(m.group(1).strip())


def has_name(text: str, name_list: list[str] | None = None) -> bool:
    return mask_title(text, name_list) != text
