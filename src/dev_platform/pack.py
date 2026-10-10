"""Deterministic release archives and safe, write-once installation.

The archive is a gzip'd tar of one top-level `<version>/` directory with normalized metadata
(sorted entries, uid/gid 0, mtime 0, fixed modes). The *tree digest* inside is reproducible
everywhere; the archive bytes are reproducible for a given Python/zlib, so the archive digest is
what gets attested, not assumed.
"""

from __future__ import annotations

import contextlib
import gzip
import hashlib
import io
import os
import re
import shutil
import tarfile
import tempfile
from pathlib import Path

from dev_platform import release
from dev_platform.digest import tree_digest
from dev_platform.errors import ConfigError

MAX_MEMBERS = 20_000
MAX_BYTES = 256 * 1024 * 1024
_VERSION = re.compile(r"^\d+\.\d+\.\d+(-[0-9A-Za-z.]+)?$")


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def pack(release_dir: Path, out_file: Path) -> str:
    """Write out_file (a .tar.gz) and return its sha256."""
    d = Path(release_dir)
    release.load(d)  # refuse to pack something that does not verify
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.PAX_FORMAT) as tar:

        def add(path: Path, arcname: str, is_dir: bool) -> None:
            info = tarfile.TarInfo(arcname)
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            info.mtime = 0
            if is_dir:
                info.type, info.mode = tarfile.DIRTYPE, 0o755
                tar.addfile(info)
            else:
                data = path.read_bytes()
                info.size, info.mode = len(data), 0o644
                tar.addfile(info, io.BytesIO(data))

        add(d, d.name, True)
        for dirpath, dirnames, filenames in os.walk(d, followlinks=False):
            dirnames[:] = sorted(x for x in dirnames if x != "__pycache__")
            for name in dirnames:
                p = Path(dirpath) / name
                if p.is_symlink():
                    raise ConfigError([f"symlink not allowed in release: {p}"])
                add(p, f"{d.name}/{p.relative_to(d).as_posix()}", True)
            for name in sorted(filenames):
                p = Path(dirpath) / name
                if name.endswith(".pyc"):
                    continue
                if p.is_symlink():
                    raise ConfigError([f"symlink not allowed in release: {p}"])
                add(p, f"{d.name}/{p.relative_to(d).as_posix()}", False)
    raw = io.BytesIO()
    with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0, compresslevel=9, filename="") as gz:
        gz.write(buf.getvalue())
    Path(out_file).write_bytes(raw.getvalue())
    return hashlib.sha256(raw.getvalue()).hexdigest()


def safe_extract(archive: Path, dest: Path) -> str:
    """Extract into `dest` rejecting anything but regular files/dirs under one `<version>/` root.

    Returns the version directory name. Nothing from the archive is executed.
    """
    total = count = 0
    root: str | None = None
    with tarfile.open(archive, mode="r:gz") as tar:
        for m in tar:
            count += 1
            total += max(m.size, 0)
            if count > MAX_MEMBERS or total > MAX_BYTES:
                raise ConfigError(["archive exceeds size/member limits"])
            if not (m.isfile() or m.isdir()):
                raise ConfigError([f"archive member {m.name!r}: only regular files and directories allowed"])
            parts = Path(m.name).parts
            if m.name.startswith("/") or ".." in parts or not parts:
                raise ConfigError([f"archive member {m.name!r}: unsafe path"])
            if root is None:
                root = parts[0]
                if not _VERSION.match(root):
                    raise ConfigError([f"archive root {root!r} is not a version"])
            elif parts[0] != root:
                raise ConfigError([f"archive member {m.name!r} outside root {root!r}"])
            target = Path(dest) / m.name
            if m.isdir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists():
                    raise ConfigError([f"duplicate archive member {m.name!r}"])
                f = tar.extractfile(m)
                assert f is not None
                target.write_bytes(f.read())
    if root is None:
        raise ConfigError(["empty archive"])
    return root


def _freeze(path: Path) -> None:
    """Make an installed release read-only (defense in depth; the digest pin is the real control)."""
    for dirpath, _dirs, filenames in os.walk(path):
        for n in filenames:
            os.chmod(Path(dirpath) / n, 0o444)
    for dirpath, _dirs, _files in sorted(os.walk(path), reverse=True):
        os.chmod(dirpath, 0o555)  # noqa: S103 - read-only, world-readable release dir  # noqa: S103 - read-only, world-readable release dir


def install(
    archive: Path, store: Path, *, expect_archive_sha256: str, expect_tree_sha256: str | None = None
) -> Path:
    """Verify an archive against expected digests and install it write-once into the store.

    Order matters: archive digest first, then extraction into a private staging directory, then
    tree digest and structural verification, and only then an atomic rename into the store.
    """
    archive = Path(archive)
    actual = file_sha256(archive)
    if actual != expect_archive_sha256:
        raise ConfigError([f"archive sha256 {actual} != expected {expect_archive_sha256}"])
    store = Path(store)
    store.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".staging-", dir=store))
    try:
        version = safe_extract(archive, staging)
        vdir = staging / version
        doc = release.load(vdir)
        if doc["platform"]["version"] != version:
            raise ConfigError(
                [f"release.json version {doc['platform']['version']} != archive root {version}"]
            )
        tree = tree_digest(vdir)
        if expect_tree_sha256 and tree != expect_tree_sha256:
            raise ConfigError([f"tree digest {tree} != expected {expect_tree_sha256}"])
        final = store / version
        if final.exists():
            if tree_digest(final) == tree:
                return final  # idempotent: same bytes already installed
            raise ConfigError([f"{final} exists with a different digest; releases are write-once"])
        os.rename(vdir, final)
        _freeze(final)
        return final
    finally:
        _unfreeze_rmtree(staging)


def _unfreeze_rmtree(path: Path) -> None:
    for dirpath, _d, _f in os.walk(path):
        with contextlib.suppress(OSError):
            os.chmod(dirpath, 0o700)
    shutil.rmtree(path, ignore_errors=True)
