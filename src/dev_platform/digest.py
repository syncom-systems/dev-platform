"""Deterministic tree digest used for release integrity pins."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

_SKIP_DIRS = {"__pycache__"}
_SKIP_SUFFIXES = (".pyc",)


def tree_digest(root: Path) -> str:
    """sha256 over sorted relative paths and file contents.

    Symlinks are rejected: a pinned tree must be self-contained. Bytecode caches
    are excluded because the interpreter creates them after installation.
    """
    root = Path(root)
    if not root.is_dir():
        raise NotADirectoryError(str(root))
    h = hashlib.sha256()
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
            rel = path.relative_to(root).as_posix().encode()
            data = path.read_bytes()
            h.update(len(rel).to_bytes(8, "big") + rel)
            h.update(len(data).to_bytes(8, "big") + data)
    return h.hexdigest()
