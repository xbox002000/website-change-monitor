"""Fetch a page, extract text, compare to KV snapshot, return result row."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx

from diffutil import diff_summary
from extract import content_hash, extract_text, normalize_text, snapshot_key

UA = "Mozilla/5.0 (compatible; WebsiteChangeMonitor/0.1; +https://apify.com)"


@dataclass
class CheckResult:
    item: dict
    ok: bool  # successful fetch + hash produced
    changed: bool
    text_for_store: str | None  # None = don't store text


async def check_url(
    url: str,
    client: httpx.AsyncClient,
    *,
    previous: dict | None,
    css_selector: str | None,
    ignore_patterns: list[str],
    max_body_bytes: int,
    timeout: float,
    store_text: bool,
    max_diff_lines: int,
    max_stored_text_chars: int,
) -> CheckResult:
    t0 = time.perf_counter()
    host = urlparse(url).hostname
    try:
        r = await client.get(url, follow_redirects=True, timeout=timeout)
        body = r.content[: max_body_bytes + 1]
        truncated_body = len(body) > max_body_bytes
        if truncated_body:
            body = body[:max_body_bytes]
        ctype = (r.headers.get("content-type") or "").split(";")[0].strip().lower()
        # Non-HTML: hash raw bytes as latin-1 text for stable change detection
        if ctype and "html" not in ctype and "xml" not in ctype and "text/" not in ctype:
            text = normalize_text(body.decode("utf-8", errors="replace"), ignore_patterns)
        else:
            text = extract_text(body, css_selector)
            text = normalize_text(text, ignore_patterns) if ignore_patterns else text
        ch = content_hash(text)
        duration_ms = int((time.perf_counter() - t0) * 1000)
        prev_hash = (previous or {}).get("contentHash")
        is_first = previous is None or prev_hash is None
        changed = (not is_first) and prev_hash != ch
        old_text = (previous or {}).get("text") if store_text or changed else None
        dsum = diff_summary(
            None if is_first else (old_text if isinstance(old_text, str) else None),
            text,
            max_lines=max_diff_lines,
        )
        # If previous had no stored text, still report hash change without unified diff
        if changed and dsum.get("unifiedDiff") is None and not is_first:
            dsum = {
                "isFirstSeen": False,
                "linesAdded": None,
                "linesRemoved": None,
                "unifiedDiff": None,
                "truncated": False,
                "note": "previous text not stored; hash differs",
            }
        item: dict[str, Any] = {
            "url": url,
            "finalUrl": str(r.url),
            "httpStatus": r.status_code,
            "ok": 200 <= r.status_code < 400,
            "contentType": ctype or None,
            "contentHash": ch,
            "previousHash": prev_hash,
            "changed": changed,
            "isFirstSeen": is_first,
            "diffSummary": dsum,
            "bodyTruncated": truncated_body,
            "textChars": len(text),
            "durationMs": duration_ms,
            "errorClass": None,
            "error": None,
            "host": host,
            "checkedAt": None,  # filled by main
            "snapshotKey": snapshot_key(url),
        }
        store = text[:max_stored_text_chars] if store_text else None
        # HTTP error statuses still produce a check (hash of error page) — treat as ok for charging
        # unless status is totally unreadable; we always hashed something here.
        return CheckResult(item=item, ok=True, changed=changed, text_for_store=store)
    except httpx.TimeoutException as e:
        return _err(url, host, t0, "timeout", f"{type(e).__name__}: {e}")
    except httpx.ConnectError as e:
        msg = str(e).lower()
        cls = "dns" if "name or service not known" in msg or "getaddrinfo" in msg or "nodename" in msg else "network"
        return _err(url, host, t0, cls, f"{type(e).__name__}: {e}")
    except httpx.HTTPError as e:
        return _err(url, host, t0, "network", f"{type(e).__name__}: {e}")
    except Exception as e:  # noqa: BLE001
        return _err(url, host, t0, "network", f"{type(e).__name__}: {e}")


def _err(url: str, host: str | None, t0: float, error_class: str, error: str) -> CheckResult:
    item = {
        "url": url,
        "finalUrl": None,
        "httpStatus": None,
        "ok": False,
        "contentType": None,
        "contentHash": None,
        "previousHash": None,
        "changed": False,
        "isFirstSeen": None,
        "diffSummary": None,
        "bodyTruncated": False,
        "textChars": 0,
        "durationMs": int((time.perf_counter() - t0) * 1000),
        "errorClass": error_class,
        "error": error[:500],
        "host": host,
        "checkedAt": None,
        "snapshotKey": snapshot_key(url),
    }
    return CheckResult(item=item, ok=False, changed=False, text_for_store=None)
