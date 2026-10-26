"""Repository files that earlier releases placed in a project and that 0.17.0 no longer uses (ADR 0027).

They are reported, never read as an operational input, deleted or changed: removing them is the project
owner's decision (a change to a file the platform does not own). `dev-platform.toml` is the pin; where a
legacy file would say something else, the toml wins.
"""

from __future__ import annotations

from pathlib import Path

from dev_platform.bazelconf import BAZELRC_HOOK, MODULE_HOOK, OUT_DIR

PINS_FILE = "dev-platform.release-pins.json"
INFRA_PROFILE = ".dev-platform/infra-profile.json"


def _has_line(path: Path, line: str) -> bool:
    try:
        return any(x.strip() == line for x in path.read_text(encoding="utf-8").splitlines())
    except (OSError, UnicodeDecodeError):
        return False


def integration_files(root: Path) -> list[dict]:
    """[{path, note}] for each legacy platform file present in `root`; read-only."""
    root = Path(root)
    found = []
    if (root / PINS_FILE).is_file():
        found.append(
            (
                PINS_FILE,
                "release identity of a pin before 0.17.0; dev-platform.toml [platform] carries it now",
            )
        )
    if (root / INFRA_PROFILE).is_file():
        found.append(
            (
                INFRA_PROFILE,
                "vendored infra profile; no longer read implicitly (pass --infra-profile explicitly)",
            )
        )
    if (root / OUT_DIR).is_dir():
        found.append(
            (
                f"{OUT_DIR}/",
                "generated Bazel files of releases before 0.17.0; verified when present, never written",
            )
        )
    for rel, line in (("MODULE.bazel", MODULE_HOOK), (".bazelrc", BAZELRC_HOOK)):
        if _has_line(root / rel, line):
            found.append((rel, "contains a platform entry line from releases before 0.17.0"))
    return [{"path": p, "note": n} for p, n in found]
