"""The output-path guard of repository isolation (ADR 0027).

A consuming project's working tree and Git metadata are never a destination of platform output. Every
caller-chosen destination (an output flag, an evidence or store location, an installation root, an
environment override) is resolved through symlinks and refused when it lies inside a protected tree.

Protected, judged two ways, so that neither the working directory nor the flags decide alone:
- from where the command runs: the directory of the nearest `dev-platform.toml` (from `--project` and from
  the working directory), the Git working tree containing it, and the Git metadata (a linked worktree's and
  the main repository's included);
- from the destination itself: any ancestor holding a `dev-platform.toml`, and any `.git` component. A
  command run from elsewhere therefore cannot write into another project, or into any Git metadata.

Containment is decided by file identity (`samefile` on each existing ancestor), not by comparing path text,
so a different spelling of the same directory (letter case on a case-insensitive volume, a bind or a link)
cannot slip through. An existing file with several hard links is refused when another link lies in a
protected tree.

The one exemption is the platform's own repository: a `dev-platform.toml` that says `self_hosted = true` AND
is the checkout the running platform code comes from (`<root>/src/dev_platform` is this very package, not a
link to it). Only the code's own location decides, never an environment variable or a flag, so a release
run by the checkout is not the checkout. The claim alone grants nothing: a consuming project, or a cloned
repository, that sets `self_hosted = true` is as protected as any other, because the code that runs is not in
it. The only writes into a project, `dev-platform.toml` by `install`, `update` and `init`, do not pass
through this guard.

Resolution is `realpath`, which follows symlinks in every existing component. The check happens immediately
before use; a path swapped concurrently by another process between check and use is not defended against.
"""

from __future__ import annotations

import os
import tomllib
from collections.abc import Iterable
from pathlib import Path

from dev_platform.config import CONFIG_FILENAME
from dev_platform.errors import ConfigError

PACKAGE_DIR = Path(os.path.realpath(Path(__file__).resolve().parent))


def _real(p: Path | str) -> Path:
    return Path(os.path.realpath(os.path.abspath(os.fspath(p))))


def _same(a: Path, b: Path) -> bool:
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False


def _inside(target: Path, root: Path) -> bool:
    """Is `target` (which need not exist) `root` or below it, by identity of an existing ancestor?"""
    return any(p.exists() and _same(p, root) for p in [target, *target.parents])


def _claims_self_hosted(toml: Path) -> bool:
    try:
        platform = tomllib.loads(toml.read_text(encoding="utf-8")).get("platform", {})
    except (OSError, ValueError):
        return False  # unreadable or invalid: protect it
    return isinstance(platform, dict) and platform.get("self_hosted") is True


def is_platform_repository(root: Path) -> bool:
    """The platform's own checkout: it claims `self_hosted` and the running code is its `src/dev_platform`.
    Nothing the caller supplies (environment, flags) takes part: only where this code was loaded from."""
    toml = root / CONFIG_FILENAME
    here = root / "src" / "dev_platform"
    return (
        toml.is_file()
        and _claims_self_hosted(toml)
        and not (root / "src").is_symlink()
        and not here.is_symlink()
        and _real(here) == PACKAGE_DIR
    )


def _git_dirs(root: Path) -> list[Path]:
    """The Git working tree containing `root` and its metadata (a `.git` file points at the real one)."""
    for d in [root, *root.parents]:
        g = d / ".git"
        if g.is_dir():
            return [d, _real(g)]
        if g.is_file():
            out = [d, _real(g)]
            try:
                line = g.read_text(encoding="utf-8").strip()
            except OSError:
                return out
            if line.startswith("gitdir:"):
                target = _real(d / line.removeprefix("gitdir:").strip())
                out.append(target)
                common = target / "commondir"  # a linked worktree shares the main repository's metadata
                if common.is_file():
                    out.append(_real(target / common.read_text(encoding="utf-8").strip()))
            return out
    return []


def protected_roots(project: Path | None = None, cwd: Path | None = None) -> list[Path]:
    starts = [Path(project)] if project is not None else []
    starts.append(Path(cwd) if cwd is not None else Path.cwd())
    roots: list[Path] = []
    for start in starts:
        start = _real(start)
        for d in [start, *start.parents]:
            if (d / CONFIG_FILENAME).is_file():
                if not is_platform_repository(d):
                    roots += [d, *_git_dirs(d)]
                break
    seen: list[Path] = []
    for r in roots:
        if r not in seen:
            seen.append(r)
    return seen


def _hardlinked_into(target: Path, roots: list[Path]) -> Path | None:
    """The root holding another hard link of the existing multiply-linked file `target`, if any."""
    try:
        st = target.stat()
    except OSError:
        return None
    if not target.is_file() or st.st_nlink < 2:
        return None
    for root in roots:
        for dirpath, _dirs, files in os.walk(root):
            for name in files:
                try:
                    o = os.stat(os.path.join(dirpath, name), follow_symlinks=False)
                except OSError:
                    continue
                if (o.st_dev, o.st_ino) == (st.st_dev, st.st_ino):
                    return root
    return None


def refusal(path: Path | str, what: str, project: Path | None = None, cwd: Path | None = None) -> str | None:
    """Why `path` may not be written (None: it may)."""
    target = _real(path)
    roots = protected_roots(project, cwd)

    def msg(where: str, root: Path | str) -> str:
        return (
            f"{what} {os.fspath(path)!r} resolves to {target}, {where} {root}: repository isolation allows "
            f"only {CONFIG_FILENAME} there (ADR 0027); choose a location outside the repository"
        )

    for root in roots:
        if _inside(target, root):
            return msg("inside the project tree or Git metadata", root)
    for anc in [target, *target.parents]:
        if anc.name == ".git":
            return msg("inside Git metadata", anc)
        if (anc / CONFIG_FILENAME).is_file() and not is_platform_repository(anc):
            return msg("inside the project tree", anc)
    if root := _hardlinked_into(target, roots):
        return msg("a hard link of a file in the project tree", root)
    return None


def guard(
    path: Path | str | None, what: str, project: Path | None = None, cwd: Path | None = None
) -> Path | None:
    """`path` unchanged when it may be written, else a ConfigError."""
    if path is None:
        return None
    if why := refusal(path, what, project, cwd):
        raise ConfigError([why])
    return Path(path)


def guard_all(
    items: Iterable[tuple[Path | str | None, str]], project: Path | None = None, cwd: Path | None = None
) -> None:
    for path, what in items:
        guard(path, what, project, cwd)
