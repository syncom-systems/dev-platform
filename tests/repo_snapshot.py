"""A byte-exact picture of a directory tree, for proving that an operation left a repository untouched.

`git status` is not enough: it ignores ignored files, empty directories, modes and timestamps. This records,
for every entry (the `.git` directory included): its type, mode, size, mtime, content hash, and a symlink's
target, without following links.
"""

import hashlib
import os
import stat
from pathlib import Path


def snapshot(root: Path) -> dict:
    root = Path(root)
    out = {}
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames.sort()
        for name in [*dirnames, *sorted(filenames)]:
            p = Path(dirpath) / name
            st = p.lstat()
            rel = str(p.relative_to(root))
            if stat.S_ISLNK(st.st_mode):
                out[rel] = ("link", os.readlink(p))
            elif stat.S_ISDIR(st.st_mode):
                out[rel] = ("dir", stat.S_IMODE(st.st_mode))
            else:
                out[rel] = (
                    "file",
                    stat.S_IMODE(st.st_mode),
                    st.st_size,
                    st.st_mtime_ns,
                    hashlib.sha256(p.read_bytes()).hexdigest(),
                )
    return out


def changed(before: dict, after: dict) -> dict:
    """{path: 'added'|'removed'|'modified'} between two snapshots."""
    out = {k: "added" for k in after.keys() - before.keys()}
    out |= {k: "removed" for k in before.keys() - after.keys()}
    out |= {k: "modified" for k in before.keys() & after.keys() if before[k] != after[k]}
    return out
