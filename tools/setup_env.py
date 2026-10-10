#!/usr/bin/env python3
"""Realize the pinned release-profile environment under ./.devenv (nothing outside the workspace).

This only *produces* bytes. Whether they are the right bytes is established independently by
`dev-platform` closure verification against toolchains/manifest.json: a wrong result fails there.
  python: the upstream python-build-standalone archive named in the manifest, hash-checked before
          extraction, extracted unmodified (no relocation rewriting, so the closure is location-independent)
  ruff:   a hash-locked wheel (tools/requirements.txt, installed with --require-hashes)
Needs: python3 >= 3.11 and uv on PATH (uv only installs the hash-locked wheel).
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROFILE = "dev-platform-release"


def platform_key() -> str:
    import platform

    return f"{sys.platform}-{platform.machine()}"


def fetch(url: str, sha256: str, dest: Path) -> None:
    if not url.startswith("https://"):
        raise SystemExit(f"refusing non-https source {url}")
    h = hashlib.sha256()
    with urllib.request.urlopen(url, timeout=120) as r, open(dest, "wb") as f:
        for chunk in iter(lambda: r.read(1 << 20), b""):
            h.update(chunk)
            f.write(chunk)
    if h.hexdigest() != sha256:
        dest.unlink()
        raise SystemExit(f"archive hash mismatch for {url}: got {h.hexdigest()}, pinned {sha256}")


def extract(archive: Path, dest: Path, strip: str) -> None:
    with tarfile.open(archive, "r:gz") as tar:
        for m in tar:
            parts = Path(m.name).parts
            if m.name.startswith("/") or ".." in parts or not (m.isfile() or m.isdir() or m.issym()):
                raise SystemExit(f"unsafe archive member {m.name!r}")
        tar.extractall(dest, filter="data")  # rejects absolute/escaping links, special files, setuid
    if strip:
        inner = dest / strip
        for child in inner.iterdir():
            child.rename(dest / child.name)
        inner.rmdir()


def install_rust_dist(src: dict, prefix: Path, archive: Path) -> None:
    """Assemble a Rust toolchain from the official dist tarball without running its install.sh: copy
    exactly the files each component's manifest.in lists, so the tree is deterministic (install.sh
    writes logs and path-dependent metadata)."""
    stage = prefix.parent / (prefix.name + ".stage")
    shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir(parents=True)
    with tarfile.open(archive, "r:xz") as tar:
        tar.extractall(stage, filter="data")
    top = next(stage.iterdir())
    for comp in src["components"]:
        cdir = top / comp
        for line in (cdir / "manifest.in").read_text().splitlines():
            kind, _, rel = line.partition(":")
            if kind not in ("file", "dir") or not rel or ".." in Path(rel).parts:
                raise SystemExit(f"unexpected manifest line {line!r} in {comp}")
            target = prefix / rel
            if kind == "dir":
                shutil.copytree(cdir / rel, target, symlinks=True, dirs_exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(cdir / rel, target, follow_symlinks=False)
    shutil.rmtree(stage)


def install_binary(src: dict, bindir: Path, dl: Path) -> Path:
    target = bindir / src["as"]
    bindir.mkdir(parents=True, exist_ok=True)
    fetch(src["url"], src["sha256"], target)
    target.chmod(0o755)
    return target


def main(argv: list[str] | None = None) -> int:
    profile = (argv if argv is not None else sys.argv[1:] or [PROFILE])[0]
    manifest = json.loads((ROOT / "toolchains" / "manifest.json").read_text())
    tools = manifest["profiles"][profile]["tools"]
    dev = ROOT / ".devenv"
    dev.mkdir(exist_ok=True)
    (dev / "dl").mkdir(exist_ok=True)
    for name, spec in sorted(tools.items()):
        src = (spec.get("source") or {}).get(platform_key())
        if not src:
            if name == "python":
                raise SystemExit(f"no pinned python source for {platform_key()}")
            continue
        if src.get("type") == "binary":
            install_binary(src, dev / "bin", dev / "dl")
            continue
        prefix = dev / name
        shutil.rmtree(prefix, ignore_errors=True)
        prefix.mkdir()
        if src.get("type") == "rust-dist":
            archive = dev / "dl" / f"{name}.tar.xz"
            fetch(src["url"], src["sha256"], archive)
            install_rust_dist(src, prefix, archive)
            continue
        archive = dev / "dl" / f"{name}.tar.gz"
        fetch(src["url"], src["sha256"], archive)
        extract(archive, prefix, src.get("strip", ""))
    if "ruff" in tools:  # the python venv carrying the hash-locked ruff wheel
        venv = dev / "venv"
        shutil.rmtree(venv, ignore_errors=True)
        subprocess.run(
            [str(dev / "python" / "bin" / "python3"), "-m", "venv", "--without-pip", str(venv)], check=True
        )
        subprocess.run(
            ["uv", "pip", "install", "--python", str(venv / "bin" / "python"), "--require-hashes", "--no-deps",
             "--no-cache", "-r", str(ROOT / "tools" / "requirements.txt")],
            check=True,
        )  # fmt: skip
    print(f"environment ready: PATH={dev / 'venv' / 'bin'}:{dev / 'bin'}:$PATH")
    return 0


if __name__ == "__main__":
    sys.exit(main())
