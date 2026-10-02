import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from diffutil import diff_summary
from extract import content_hash, extract_text, normalize_text, snapshot_key


def test_extract_strips_script():
    html = "<html><body><script>evil()</script><p>Hello</p><style>x{}</style><p>World</p></body></html>"
    t = extract_text(html)
    assert "evil" not in t
    assert "Hello" in t and "World" in t


def test_css_selector():
    html = "<html><body><main><p>Keep</p></main><footer>Drop</footer></body></html>"
    t = extract_text(html, "main")
    assert "Keep" in t
    assert "Drop" not in t


def test_ignore_and_hash_stable():
    a = normalize_text("Price 10\nUpdated 2026-10-01", [r"Updated .*"])
    b = normalize_text("Price 10\nUpdated 2026-10-02", [r"Updated .*"])
    assert content_hash(a) == content_hash(b)


def test_diff_first_and_change():
    d0 = diff_summary(None, "a\nb")
    assert d0["isFirstSeen"] is True
    d1 = diff_summary("a\nb", "a\nc")
    assert d1["linesAdded"] == 1 and d1["linesRemoved"] == 1
    assert "c" in (d1["unifiedDiff"] or "")


def test_snapshot_key_stable():
    assert snapshot_key("https://example.com/") == snapshot_key("https://example.com/")
    assert snapshot_key("https://a/") != snapshot_key("https://b/")


if __name__ == "__main__":
    test_extract_strips_script()
    test_css_selector()
    test_ignore_and_hash_stable()
    test_diff_first_and_change()
    test_snapshot_key_stable()
    print("ok")
