"""Runtime-closure identity for tools.

A version string or the digest of one executable does not identify what actually runs: an
interpreter also executes its standard library and extension modules. A *closure* is the set of
bytes a tool needs, expressed as either one file or one install prefix, plus a declared bound on what
those bytes may load from outside themselves (system libraries). Verification then establishes:

  1. the closure's canonical digest equals the digest pinned in the release's toolchain manifest, and
  2. every native object inside it links only to objects inside it or to the declared system
     libraries.

What this does NOT establish is stated in the result: system libraries are trusted by name/prefix,
not by content, and objects loaded dynamically at run time (dlopen) are covered only if they are
inside the closure digest.
"""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from dev_platform.errors import ConfigError

_SKIP_DIRS = {"__pycache__"}
_SKIP_SUFFIXES = (".pyc",)
MACHO_MAGICS = {
    b"\xfe\xed\xfa\xce",
    b"\xfe\xed\xfa\xcf",
    b"\xce\xfa\xed\xfe",
    b"\xcf\xfa\xed\xfe",
    b"\xca\xfe\xba\xbe",
    b"\xbe\xba\xfe\xca",
}
ELF_MAGIC = b"\x7fELF"
# Native-object dependency lister: path -> dependency names, or None when it cannot be determined.
Linkage = Callable[[Path], "list[str] | None"]


def _files(root: Path):
    """(relpath, kind, payload, executable) in canonical order. kind is 'f' or 'l'."""
    root = Path(root)
    if root.is_file():
        yield "", "f", root.read_bytes(), os.access(root, os.X_OK)
        return
    if not root.is_dir():
        raise ConfigError([f"closure root {root} does not exist"])
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS)
        entries = [(n, True) for n in filenames] + [
            (d, False) for d in dirnames if (Path(dirpath) / d).is_symlink()
        ]
        for name, _ in sorted(entries):
            if name.endswith(_SKIP_SUFFIXES):
                continue
            p = Path(dirpath) / name
            rel = p.relative_to(root).as_posix()
            if p.is_symlink():
                target = os.readlink(p)
                resolved = (p.parent / target).resolve()
                if os.path.isabs(target) or not resolved.is_relative_to(root.resolve()):
                    raise ConfigError([f"closure {root}: symlink {rel} -> {target} leaves the closure"])
                yield rel, "l", target.encode(), False
            else:
                yield rel, "f", p.read_bytes(), os.access(p, os.X_OK)


def digest(root: Path) -> tuple[str, int]:
    """Canonical digest of a file or tree, including symlink targets and executable bits.

    A single file is identified by the plain sha256 of its bytes, so the pin can be compared with the
    publisher's own digest.
    """
    if Path(root).is_file():
        return hashlib.sha256(Path(root).read_bytes()).hexdigest(), 1
    h, n = hashlib.sha256(), 0
    for rel, kind, payload, exe in _files(root):
        b = rel.encode()
        h.update(kind.encode() + (b"x" if exe else b"-") + len(b).to_bytes(8, "big") + b)
        h.update(len(payload).to_bytes(8, "big") + payload)
        n += 1
    return h.hexdigest(), n


def is_native(path: Path) -> bool:
    try:
        with open(path, "rb") as f:
            magic = f.read(4)
    except OSError:
        return False
    return magic == ELF_MAGIC or magic in MACHO_MAGICS


def native_objects(root: Path) -> list[Path]:
    root = Path(root)
    if root.is_file():
        return [root] if is_native(root) else []
    return sorted(
        p
        for p in root.rglob("*")
        if p.is_file() and not p.is_symlink() and "__pycache__" not in p.parts and is_native(p)
    )


def default_linkage(path: Path) -> list[str] | None:
    """Direct dependencies of one native object via the platform's own inspector."""
    with open(path, "rb") as f:
        magic = f.read(4)
    if magic == ELF_MAGIC:
        argv = ["readelf", "-d", str(path)]
        pat = re.compile(r"\(NEEDED\)\s+Shared library: \[([^\]]+)\]")
    else:
        argv = ["otool", "-L", str(path)]
        pat = re.compile(r"^\s+(\S+) \(compatibility", re.M)
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    if r.returncode != 0:
        return None
    return pat.findall(r.stdout)


def check_linkage(root: Path, system_libs: list[str], linkage: Linkage = default_linkage) -> dict:
    """Every native object may depend only on closure members or declared system libraries.

    A dependency is allowed if it begins with a declared system prefix, equals a declared system
    soname, or (for @rpath/@loader_path/@executable_path and bare sonames) its basename exists inside
    the closure. Anything else - or an object whose dependencies cannot be listed - fails closed.
    """
    root = Path(root)
    base = root.parent if root.is_file() else root
    members = [root] if root.is_file() else root.rglob("*")
    inside = {p.name for p in members if p.is_file() or p.is_symlink()}
    violations, unknown, objects = [], [], native_objects(root)
    for obj in objects:
        deps = linkage(obj)
        rel = obj.relative_to(base).as_posix() if obj != root else obj.name
        if deps is None:
            unknown.append(rel)
            continue
        for dep in deps:
            if any(dep.startswith(s) or dep == s for s in system_libs):
                continue
            if os.path.basename(dep) in inside and (dep.startswith(("@", "$ORIGIN")) or "/" not in dep):
                continue
            if os.path.isabs(dep) and Path(dep).resolve().is_relative_to(base.resolve()):
                continue  # install name / dependency that points back into the closure
            violations.append(f"{rel} -> {dep}")
    return {"native_objects": len(objects), "violations": violations, "unknown": unknown}


def resolve_root(spec: dict, executable: str | None) -> Path | None:
    """The closure root for a tool: the executable itself, or an ancestor of its real path."""
    if executable is None:
        return None
    real = Path(executable).resolve()
    if spec["kind"] == "file":
        return real
    return real.parents[spec["prefix_up"] - 1]


def platform_key() -> str:
    import platform

    return f"{sys.platform}-{platform.machine()}"


def validate(w: str, c: object) -> list[str]:
    if not isinstance(c, dict):
        return [f"{w}.closure must be an object"]
    errs = []
    if c.get("kind") not in ("file", "prefix"):
        errs.append(f"{w}.closure.kind: file|prefix")
    if c.get("kind") == "prefix" and not (isinstance(c.get("prefix_up"), int) and c["prefix_up"] >= 1):
        errs.append(f"{w}.closure.prefix_up: integer >= 1 (levels above the executable's real path)")
    sha = c.get("sha256")
    if not isinstance(sha, dict) or not sha:
        errs.append(f"{w}.closure.sha256: map of '<sys.platform>-<machine>' to 64 hex chars")
    else:
        for k, v in sha.items():
            if not (isinstance(v, str) and re.fullmatch(r"[0-9a-f]{64}", v)):
                errs.append(f"{w}.closure.sha256[{k}]: 64 hex chars")
    libs = c.get("system_libs")
    if not isinstance(libs, list) or not all(isinstance(x, str) and x for x in libs):
        errs.append(f"{w}.closure.system_libs: list of allowed system library prefixes/sonames")
    return errs
