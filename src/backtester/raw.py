"""Immutable raw downloads and the manifest that records them.

Invariant 7: a raw file is never overwritten. ``store_raw`` refuses if the
target exists, and every stored file is appended to ``manifest.json`` with
its URL, sha256, size and fetch time, so a run can be reproduced from the
manifest even though the bytes are not in git.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import requests

MANIFEST = "manifest.json"
USER_AGENT = "backtester-research/0.1 (github.com/utkarsh; factor research)"


def store_raw(raw_root: Path, rel_path: str, content: bytes, url: str) -> Path:
    """Write ``content`` to ``raw_root/rel_path`` and record it.

    Refuses to overwrite an existing file.
    """
    dest = raw_root / rel_path
    if dest.exists():
        raise FileExistsError(
            f"{dest} already exists; raw files are never overwritten (invariant 7)"
        )
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(content)

    entry = {
        "path": rel_path.replace("\\", "/"),
        "url": url,
        "sha256": hashlib.sha256(content).hexdigest(),
        "bytes": len(content),
        "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    manifest = raw_root / MANIFEST
    entries = json.loads(manifest.read_text()) if manifest.exists() else []
    entries.append(entry)
    manifest.write_text(json.dumps(entries, indent=2) + "\n")
    return dest


def fetch_to_raw(raw_root: Path, rel_path: str, url: str, *, timeout: int = 60) -> Path:
    """GET ``url`` and store it under ``raw_root/rel_path``."""
    r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=timeout)
    r.raise_for_status()
    return store_raw(raw_root, rel_path, r.content, url)


def latest(raw_root: Path, pattern: str) -> Path:
    """The lexically last file matching ``pattern``; date-stamped names sort by date."""
    matches = sorted(raw_root.glob(pattern))
    if not matches:
        raise FileNotFoundError(f"no raw file matches {pattern} under {raw_root}")
    return matches[-1]
