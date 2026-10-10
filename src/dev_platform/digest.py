"""Deterministic tree digest and verified snapshots for release integrity."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Iterator
from pathlib import Path

_SKIP_DIRS = {"__pycache__"}
_SKIP_SUFFIXES = (".pyc",)


def _entries(root: Path) -> Iterator[tuple[str, bytes]]:
    """Yield (relative path, content) in canonical order. Symlinks are rejected: a pinned tree
    must be self-contained. Bytecode caches are excluded (created after installation)."""
    root = Path(root)
    if not root.is_dir():
        raise NotADirectoryError(str(root))
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        for d in dirnames:
            if (Path(dirpath) / d).is_symlink():
                raise ValueError(f"symlink in pinned tree: {Path(dirpath) / d}")
        dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS)
        for name in sorted(filenames):
            if name.endswith(_SKIP_SUFFIXES):
                continue
            path = Path(dirpath) / name
            if path.is_symlink():
                raise ValueError(f"symlink in pinned tree: {path}")
            yield path.relative_to(root).as_posix(), path.read_bytes()


def _feed(h, rel: str, data: bytes) -> None:
    b = rel.encode()
    h.update(len(b).to_bytes(8, "big") + b)
    h.update(len(data).to_bytes(8, "big") + data)


def tree_digest(root: Path) -> str:
    h = hashlib.sha256()
    for rel, data in _entries(root):
        _feed(h, rel, data)
    return h.hexdigest()


def snapshot(root: Path, dest: Path) -> str:
    """Copy `root` into the private directory `dest`, hashing the exact bytes copied.

    The returned digest describes what is in `dest`, so callers verify the digest and then execute
    from `dest`: there is no window between verification and use in which the source can change.
    """
    h = hashlib.sha256()
    for rel, data in _entries(root):
        _feed(h, rel, data)
        target = Path(dest) / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o400)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
    return h.hexdigest()
