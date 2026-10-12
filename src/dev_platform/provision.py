"""Provision the pinned toolchains of a manifest profile into a workspace-local, version-keyed store.

This only *produces* bytes. Whether they are the right bytes is established independently by closure
verification against the manifest (`toolchain verify`): a wrong result fails there. Sources are the https URLs
and sha256 pins named in the manifest; archives are hash-checked before extraction and extracted with the
"data" filter (no absolute/escaping members, links or special files).

Layout: <dev>/tools/<name>/<version>/ (versions coexist; installing one never modifies another);
<dev>/<name> and <dev>/bin/<exe> are symlink selectors only.
"""

from __future__ import annotations

import hashlib
import os
import platform
import shutil
import sys
import tarfile
import urllib.request
from pathlib import Path

from .errors import ConfigError


def platform_key() -> str:
    return f"{sys.platform}-{platform.machine()}"


def fetch(url: str, sha256: str, dest: Path) -> None:
    if not url.startswith("https://"):
        raise ConfigError([f"refusing non-https source {url}"])
    h = hashlib.sha256()
    # https only (enforced above) and digest-pinned
    with urllib.request.urlopen(url, timeout=120) as r, open(dest, "wb") as f:  # noqa: S310
        for chunk in iter(lambda: r.read(1 << 20), b""):
            h.update(chunk)
            f.write(chunk)
    if h.hexdigest() != sha256:
        dest.unlink()
        raise ConfigError([f"archive hash mismatch for {url}: got {h.hexdigest()}, pinned {sha256}"])


def extract(archive: Path, dest: Path, strip: str) -> None:
    with tarfile.open(archive, "r:gz") as tar:
        for m in tar:
            parts = Path(m.name).parts
            if m.name.startswith("/") or ".." in parts or not (m.isfile() or m.isdir() or m.issym()):
                raise ConfigError([f"unsafe archive member {m.name!r}"])
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
                raise ConfigError([f"unexpected manifest line {line!r} in {comp}"])
            target = prefix / rel
            if kind == "dir":
                shutil.copytree(cdir / rel, target, symlinks=True, dirs_exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(cdir / rel, target, follow_symlinks=False)
    shutil.rmtree(stage)


def install_binary(src: dict, bindir: Path) -> Path:
    target = bindir / src["as"]
    bindir.mkdir(parents=True, exist_ok=True)
    fetch(src["url"], src["sha256"], target)
    target.chmod(0o755)
    return target


def version_dir(dev: Path, name: str, version: str) -> Path:
    """Every pinned version of a tool lives in its own directory, so versions coexist and installing
    one never modifies another."""
    return dev / "tools" / name / version


def activate(link: Path, target: Path) -> None:
    """Point the stable name (`<dev>/<name>`, `<dev>/bin/<exe>`) at one installed version. The link is only a
    selector: verification resolves real paths, so identity is always that of the version directory."""
    if link.is_symlink() or link.is_file():
        link.unlink()
    elif link.is_dir():
        shutil.rmtree(link)
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(target.resolve())


def provision(manifest: dict, profile: str, dev: Path, *, key: str | None = None) -> list[str]:
    """Realize every tool of `profile` that has a pinned source for this platform; returns the names
    installed. Tools without a source here (for example a venv-installed wheel) are left to the caller."""
    key = key or platform_key()
    if profile not in manifest["profiles"]:
        raise ConfigError([f"profile {profile!r} not in manifest (have {sorted(manifest['profiles'])})"])
    tools = manifest["profiles"][profile]["tools"]
    dev.mkdir(parents=True, exist_ok=True)
    (dev / "dl").mkdir(exist_ok=True)
    done = []
    for name, spec in sorted(tools.items()):
        src = (spec.get("source") or {}).get(key)
        if not src:
            if name == "python":
                raise ConfigError([f"no pinned python source for {key}"])
            continue
        vdir = version_dir(dev, name, spec["version"])
        if src.get("type") == "binary":
            install_binary(src, vdir / "bin")
            activate(dev / "bin" / src["as"], vdir / "bin" / src["as"])
            done.append(name)
            continue
        shutil.rmtree(vdir, ignore_errors=True)
        vdir.mkdir(parents=True)
        if src.get("type") == "rust-dist":
            archive = dev / "dl" / f"{name}-{spec['version']}.tar.xz"
            fetch(src["url"], src["sha256"], archive)
            install_rust_dist(src, vdir, archive)
        else:
            archive = dev / "dl" / f"{name}-{spec['version']}.tar.gz"
            fetch(src["url"], src["sha256"], archive)
            extract(archive, vdir, src.get("strip", ""))
        activate(dev / name, vdir)
        done.append(name)
    return done


def tool_dirs(dev: Path) -> list[str]:
    """The directories a provisioned environment puts on PATH, in order."""
    return [str(dev / "bin")] + [str(p / "bin") for p in sorted(dev.iterdir()) if (p / "bin").is_dir()]


def provision_and_verify(manifest: dict, profile: str, dev: Path, root: Path) -> tuple[list[str], dict]:
    """Realize the pinned profile and verify the provisioned tools against the same manifest, with the
    provisioned directories first on PATH. Returns (installed, environment record). The record's
    `identity_digest` is the identity of the realized environment: provisioning the same release twice,
    anywhere, must give the same digest."""
    from . import toolchain  # local import: provisioning must not depend on verification at import time

    done = provision(manifest, profile, dev)
    saved = os.environ.get("PATH", "")
    os.environ["PATH"] = os.pathsep.join([*tool_dirs(dev), saved])
    try:
        rec = toolchain.verify_profile(manifest, profile, root)
    finally:
        os.environ["PATH"] = saved
    return done, rec
