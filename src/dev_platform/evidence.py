"""Write-once, content-addressed store for evidence records (results, app releases, authorizations).

A record is stored under its canonical digest (records.canonical_digest). The name IS the claim, so every
read re-derives the digest and a mismatch is corruption, never silently served. Nothing is overwritten or
deleted by this module; files are made read-only. This is local storage, not a trust anchor: it makes
records tamper-evident to whoever holds their digests (an app-release record names its evidence digests).
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

from dev_platform.errors import ConfigError
from dev_platform.records import canonical_digest


def _path(store: Path, digest: str) -> Path:
    return Path(store) / digest[:2] / f"{digest}.json"


def put(store: Path, doc: dict) -> str:
    digest = canonical_digest(doc)
    p = _path(store, digest)
    if p.exists():
        if canonical_digest(json.loads(p.read_text())) != digest:
            raise ConfigError([f"evidence {digest} exists but its content does not match (corrupt store)"])
        return digest
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(json.dumps(doc, indent=2, sort_keys=True) + "\n")
    tmp.chmod(stat.S_IRUSR)
    os.rename(tmp, p)
    return digest


def get(store: Path, digest: str) -> dict:
    p = _path(store, digest)
    try:
        doc = json.loads(p.read_text())
    except (OSError, json.JSONDecodeError) as e:
        raise ConfigError([f"evidence {digest}: {e}"]) from None
    if canonical_digest(doc) != digest:
        raise ConfigError([f"evidence {digest}: content does not match its digest (corrupt)"])
    return doc


def scan(store: Path) -> tuple[dict[str, dict], list[str]]:
    """(digest -> record for every intact file, problems for every corrupt or misnamed one)."""
    good: dict[str, dict] = {}
    bad: list[str] = []
    root = Path(store)
    if not root.is_dir():
        return good, bad
    for p in sorted(root.glob("*/*.json")):
        digest = p.stem
        try:
            doc = json.loads(p.read_text())
        except (OSError, json.JSONDecodeError):
            bad.append(f"{digest}: unreadable")
            continue
        if canonical_digest(doc) != digest or p.parent.name != digest[:2]:
            bad.append(f"{digest}: content does not match its name")
        else:
            good[digest] = doc
    return good, bad
