"""Invariant 7: raw files are never overwritten, and every one is in the manifest."""

import json
from pathlib import Path

import pytest

from backtester import raw


def test_fetch_refuses_to_overwrite_raw(tmp_path: Path) -> None:
    raw.store_raw(tmp_path, "src/a.html", b"first", "http://x/a")
    with pytest.raises(FileExistsError):
        raw.store_raw(tmp_path, "src/a.html", b"second", "http://x/a")
    assert (tmp_path / "src/a.html").read_bytes() == b"first"


def test_every_store_appends_to_manifest(tmp_path: Path) -> None:
    raw.store_raw(tmp_path, "a.html", b"first", "http://x/a")
    raw.store_raw(tmp_path, "b/b.html", b"second", "http://x/b")
    entries = json.loads((tmp_path / raw.MANIFEST).read_text())
    assert [e["path"] for e in entries] == ["a.html", "b/b.html"]
    assert entries[0]["bytes"] == 5 and len(entries[0]["sha256"]) == 64
    assert entries[1]["url"] == "http://x/b"


def test_latest_picks_the_newest_datestamp(tmp_path: Path) -> None:
    for d in ("2026-01-05", "2026-03-01", "2025-12-31"):
        raw.store_raw(tmp_path, f"w/page_{d}.html", b"x", "http://x")
    assert raw.latest(tmp_path, "w/page_*.html").name == "page_2026-03-01.html"
