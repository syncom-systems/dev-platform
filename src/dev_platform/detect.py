"""Discovery of facts about a repository.

Detection reports what exists. It never decides what is *required*: assurance
level, mandatory checks and build-system policy come only from configuration.
"""

from __future__ import annotations

import os
from pathlib import Path

_EXT_LANG = {".py": "python", ".rs": "rust", ".sh": "shell", ".bzl": "starlark"}
_SKIP = {".git", "node_modules", "target", ".venv", "venv", "__pycache__"}
_BAZEL_MARKERS = ("MODULE.bazel", "WORKSPACE", "WORKSPACE.bazel")
_BAZEL_PACKAGE = ("BUILD", "BUILD.bazel")


def detect(root: Path) -> dict:
    root = Path(root)
    languages: dict[str, int] = {}
    markers: dict[str, list[str]] = {}

    def mark(system: str, rel: str) -> None:
        markers.setdefault(system, []).append(rel)

    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if d not in _SKIP and not d.startswith("bazel-"))
        rel_dir = Path(dirpath).relative_to(root)
        for name in sorted(filenames):
            rel = (rel_dir / name).as_posix()
            lang = _EXT_LANG.get(Path(name).suffix)
            if lang:
                languages[lang] = languages.get(lang, 0) + 1
            if name in _BAZEL_MARKERS or name in _BAZEL_PACKAGE:
                mark("bazel", rel)
            elif name == "Cargo.toml":
                mark("cargo", rel)
            elif name in ("pyproject.toml", "setup.py", "requirements.txt"):
                mark("python-packaging", rel)
    return {
        "schema": "dev-platform.facts/v1",
        "languages": dict(sorted(languages.items())),
        "build_systems": {k: sorted(v) for k, v in sorted(markers.items())},
        "note": "discovered facts only; required verification is declared in dev-platform.toml",
    }


def is_bazel_workspace(facts: dict) -> bool:
    return any(Path(m).name in _BAZEL_MARKERS for m in facts["build_systems"].get("bazel", []))
