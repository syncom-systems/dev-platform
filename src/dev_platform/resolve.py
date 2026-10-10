"""Platform version resolution and integrity verification (the launcher core).

No global mutable state: versions live side by side, immutable, in a store the
launcher only reads. A consumer pins an exact version plus a tree digest.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import dev_platform
from dev_platform.config import Config
from dev_platform.digest import tree_digest
from dev_platform.errors import PlatformResolutionError

OVERRIDE_ENV = "DEV_PLATFORM_OVERRIDE"
STORE_ENV = "DEV_PLATFORM_STORE"
REEXEC_ENV = "DEV_PLATFORM_REEXEC"
PACKAGE_ROOT = Path(dev_platform.__file__).resolve().parent.parent  # .../src


@dataclass(frozen=True)
class Resolution:
    mode: str  # "pinned" | "override" | "self"
    version: str | None
    root: Path | None  # directory containing the dev_platform package (a `src` dir)
    digest: str | None

    @property
    def certifiable(self) -> bool:
        return self.mode in ("pinned", "self")


def protected_context(env=os.environ, flag: bool = False) -> bool:
    return flag or env.get("CI", "").lower() in ("1", "true") or env.get("GITHUB_ACTIONS") == "true"


def default_store(env=os.environ) -> Path:
    if env.get(STORE_ENV):
        return Path(env[STORE_ENV])
    base = env.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "dev-platform" / "versions"


def resolve(cfg: Config, *, env=os.environ, protected: bool = False) -> Resolution:
    override = env.get(OVERRIDE_ENV)
    if override:
        if protected_context(env, protected):
            raise PlatformResolutionError(
                f"{OVERRIDE_ENV} is set in a protected context (CI or --protected); "
                "overrides may not influence protected runs or certification"
            )
        root = Path(override) / "src"
        if not (root / "dev_platform").is_dir():
            raise PlatformResolutionError(f"{OVERRIDE_ENV}={override}: no src/dev_platform inside")
        return Resolution("override", None, root.resolve(), None)

    pin = cfg.platform
    if pin.self_hosted:
        return Resolution("self", dev_platform.__version__, PACKAGE_ROOT, None)

    vdir = default_store(env) / pin.version
    if not vdir.is_dir():
        raise PlatformResolutionError(
            f"platform {pin.version} is not installed in {vdir.parent} (fetch it with the "
            "launcher/bootstrap documented in docs/distribution.md)"
        )
    try:
        actual = tree_digest(vdir)
    except (OSError, ValueError) as e:
        raise PlatformResolutionError(f"cannot digest {vdir}: {e}") from None
    if actual != pin.sha256:
        raise PlatformResolutionError(
            f"integrity failure for platform {pin.version}: pinned sha256 {pin.sha256}, "
            f"installed tree is {actual}"
        )
    root = vdir / "src"
    if not (root / "dev_platform").is_dir():
        raise PlatformResolutionError(f"{vdir}: malformed release (no src/dev_platform)")
    return Resolution("pinned", pin.version, root.resolve(), actual)


def needs_reexec(res: Resolution, env=os.environ) -> bool:
    """True when the resolved release is not the code currently running.

    Raises if we were already re-executed and still do not match (no loops).
    """
    if res.root is None or res.root == PACKAGE_ROOT:
        return False
    if env.get(REEXEC_ENV):
        raise PlatformResolutionError(
            f"re-executed into {env[REEXEC_ENV]} but running code is {PACKAGE_ROOT}, not {res.root}"
        )
    return True


def reexec_env(res: Resolution, env=os.environ) -> dict[str, str]:
    e = dict(env)
    e["PYTHONPATH"] = str(res.root)
    e["PYTHONDONTWRITEBYTECODE"] = "1"  # keep the pinned tree byte-identical
    e[REEXEC_ENV] = res.version or res.mode
    return e
