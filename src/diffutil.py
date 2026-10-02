"""Text diff helpers using stdlib difflib — no paid LLM."""
from __future__ import annotations

import difflib


def diff_summary(
    old: str | None,
    new: str,
    *,
    max_lines: int = 40,
    context: int = 2,
) -> dict:
    """Return unified-diff snippet + line counts. Empty old → first-seen (no change)."""
    if old is None:
        new_lines = new.splitlines()
        return {
            "isFirstSeen": True,
            "linesAdded": len(new_lines),
            "linesRemoved": 0,
            "unifiedDiff": None,
            "truncated": False,
        }
    old_lines = old.splitlines()
    new_lines = new.splitlines()
    ud = list(
        difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile="previous",
            tofile="current",
            lineterm="",
            n=context,
        )
    )
    # Count +/- excluding file headers
    added = removed = 0
    for line in ud:
        if line.startswith("+++") or line.startswith("---") or line.startswith("@@"):
            continue
        if line.startswith("+"):
            added += 1
        elif line.startswith("-"):
            removed += 1
    truncated = False
    if len(ud) > max_lines:
        ud = ud[:max_lines]
        truncated = True
    return {
        "isFirstSeen": False,
        "linesAdded": added,
        "linesRemoved": removed,
        "unifiedDiff": "\n".join(ud) if ud else "",
        "truncated": truncated,
    }
