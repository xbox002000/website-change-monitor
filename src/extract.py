"""HTML → normalized text for hashing / diff. Open-source stack only (selectolax MIT + stdlib)."""
from __future__ import annotations

import hashlib
import re
from typing import Iterable

from selectolax.parser import HTMLParser

# Tags whose content is noise for change detection
_DROP_TAGS = ("script", "style", "noscript", "svg", "iframe", "template")
_WS_RE = re.compile(r"[ \t\f\v]+")
_BLANK_RE = re.compile(r"\n{3,}")


def extract_text(html: str | bytes, css_selector: str | None = None) -> str:
    """Return visible-ish text. If css_selector is set, only that subtree; else body (or whole doc)."""
    if isinstance(html, bytes):
        html = html.decode("utf-8", errors="replace")
    tree = HTMLParser(html)
    for tag in _DROP_TAGS:
        for node in tree.css(tag):
            node.decompose()
    if css_selector:
        parts: list[str] = []
        for node in tree.css(css_selector):
            t = node.text(separator="\n", strip=True)
            if t:
                parts.append(t)
        raw = "\n".join(parts)
    else:
        body = tree.body
        raw = (body.text(separator="\n", strip=True) if body else tree.text(separator="\n", strip=True)) or ""
    return normalize_text(raw)


def normalize_text(text: str, ignore_patterns: Iterable[str] | None = None) -> str:
    """Collapse whitespace and strip ignore-regex matches (timestamps, CSRF tokens, etc.)."""
    s = text.replace("\r\n", "\n").replace("\r", "\n")
    if ignore_patterns:
        for pat in ignore_patterns:
            if not pat:
                continue
            try:
                s = re.sub(pat, "", s, flags=re.MULTILINE)
            except re.error:
                continue
    lines = [_WS_RE.sub(" ", ln).strip() for ln in s.split("\n")]
    lines = [ln for ln in lines if ln]
    s = "\n".join(lines)
    return _BLANK_RE.sub("\n\n", s).strip()


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def snapshot_key(url: str) -> str:
    """Stable KV key for a URL (sha256 hex; avoids illegal key chars)."""
    return "snap_" + hashlib.sha256(url.encode("utf-8")).hexdigest()
