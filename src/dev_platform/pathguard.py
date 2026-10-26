"""The output-path guard of repository isolation (ADR 0027).

A consuming project's working tree and Git metadata are never a destination of platform output. Every
caller-chosen destination (an output flag, an evidence or store location, an installation root, an
environment override) is resolved through symlinks and refused when it lies inside a protected tree.

Protected: the directory of the nearest `dev-platform.toml` (from the explicit project and from the working
directory), the Git working tree containing it, and the Git metadata directories (including a linked
worktree's). Not protected: the platform's own repository (`[platform] self_hosted`), whose maintainer and
build operations legitimately write there. The only writes into a project, `dev-platform.toml` by `install`,
`update` and `init`, do not pass through this guard.

Resolution is `realpath` of the destination, which follows symlinks in every existing component, so a link
that leads into the project is judged by its target. The check happens immediately before use; a path
changed concurrently by another process between check and use is not defended against.
"""

from __future__ import annotations

import os
import tomllib
from collections.abc import Iterable
from pathlib import Path

from dev_platform.config import CONFIG_FILENAME
from dev_platform.errors import ConfigError


def _real(p: Path | str) -> Path:
    return Path(os.path.realpath(os.path.abspath(os.fspath(p))))


def _self_hosted(toml: Path) -> bool:
    try:
        platform = tomllib.loads(toml.read_text(encoding="utf-8")).get("platform", {})
    except (OSError, ValueError):
        return False  # unreadable or invalid: protect it
    return isinstance(platform, dict) and platform.get("self_hosted") is True


def _git_dirs(root: Path) -> list[Path]:
    """The Git working tree containing `root` and its metadata (a `.git` file points at the real one)."""
    out: list[Path] = []
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
    return out


def protected_roots(project: Path | None = None, cwd: Path | None = None) -> list[Path]:
    starts = [Path(project)] if project is not None else []
    starts.append(Path(cwd) if cwd is not None else Path.cwd())
    roots: list[Path] = []
    for start in starts:
        start = _real(start)
        for d in [start, *start.parents]:
            toml = d / CONFIG_FILENAME
            if toml.is_file():
                if not _self_hosted(toml):
                    roots += [d, *_git_dirs(d)]
                break
    seen: list[Path] = []
    for r in roots:
        if r not in seen:
            seen.append(r)
    return seen


def refusal(path: Path | str, what: str, project: Path | None = None, cwd: Path | None = None) -> str | None:
    """Why `path` may not be written (None: it may)."""
    target = _real(path)
    for root in protected_roots(project, cwd):
        if target == root or root in target.parents:
            return (
                f"{what} {os.fspath(path)!r} resolves to {target}, inside the project tree or Git metadata "
                f"{root}: repository isolation allows only {CONFIG_FILENAME} there (ADR 0027); choose a "
                "location outside the repository"
            )
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
