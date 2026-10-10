"""Adapters turn a check definition into a deterministic command.

An adapter is a pure function from (check, project facts) to a Command. There is
deliberately no plugin registry yet: four built-in adapters, one dict.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from dev_platform.config import Check
from dev_platform.errors import ConfigError

PYTHON = "{python}"  # substituted with the running interpreter at execution time


@dataclass(frozen=True)
class Command:
    argv: tuple[str, ...]
    env: tuple[tuple[str, str], ...] = ()


def _python(check: Check, root: Path) -> Command:
    start = check.targets[0] if check.targets else "tests"
    paths = ".:src" if (root / "src").is_dir() else "."
    return Command((PYTHON, "-m", "unittest", "discover", "-s", start), (("PYTHONPATH", paths),))


def _bazel(check: Check, root: Path) -> Command:
    # --lockfile_mode=error: a module graph that differs from MODULE.bazel.lock fails the build instead
    # of silently re-resolving, so the lock file the platform reconciled is the graph that executes.
    return Command(("bazel", "test", "--lockfile_mode=error", "--test_output=errors", *check.targets))


def _cargo(check: Check, root: Path) -> Command:
    pkgs = [a for t in check.targets for a in ("-p", t)]
    return Command(("cargo", "test", "--locked", *pkgs))


def _exec(check: Check, root: Path) -> Command:
    return Command(check.argv)


_ADAPTERS = {"python": _python, "bazel": _bazel, "cargo": _cargo, "exec": _exec}


def command_for(check: Check, root: Path) -> Command:
    try:
        return _ADAPTERS[check.adapter](check, root)
    except KeyError:
        raise ConfigError([f"check {check.id}: no adapter {check.adapter!r}"]) from None
