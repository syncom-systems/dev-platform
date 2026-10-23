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

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from dev_platform.errors import ConfigError  # noqa: E402
from dev_platform.provision import (  # noqa: E402  (the same code consumers use: `toolchain provision`)
    activate,
    extract,
    fetch,
    install_binary,
    install_rust_dist,
    platform_key,
    provision,
    version_dir,
)

PROFILE = "dev-platform-release"

__all__ = [
    "activate",
    "extract",
    "fetch",
    "install_binary",
    "install_rust_dist",
    "platform_key",
    "version_dir",
]


def main(argv: list[str] | None = None) -> int:
    profile = (argv if argv is not None else sys.argv[1:] or [PROFILE])[0]
    manifest = json.loads((ROOT / "toolchains" / "manifest.json").read_text())
    tools = manifest["profiles"][profile]["tools"]
    dev = ROOT / ".devenv"
    dev.mkdir(exist_ok=True)
    try:
        provision(manifest, profile, dev)
    except ConfigError as e:
        raise SystemExit(str(e)) from None
    if "ruff" in tools and not tools["ruff"].get("source"):  # the venv carrying the hash-locked ruff wheel
        venv = dev / "venv"
        shutil.rmtree(venv, ignore_errors=True)
        subprocess.run(
            [
                str(version_dir(dev, "python", tools["python"]["version"]) / "bin" / "python3"),
                "-m",
                "venv",
                "--without-pip",
                str(venv),
            ],
            check=True,
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
