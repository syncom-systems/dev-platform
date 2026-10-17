"""Where a user's or job's platform releases, toolchains and caches live (not in dev-platform.toml, ADR 0003).

Each location is its command-line flag, else its environment variable, else under the data root. The data root
is `--home`, else `DEV_PLATFORM_HOME`, else in CI a job-local `$RUNNER_TEMP/dev-platform` (a job never uses
releases or toolchains that another job left in a shared home), else
`${XDG_DATA_HOME:-~/.local/share}/dev-platform`.

  store       <root>/versions/<version>/              write-once verified releases (DEV_PLATFORM_STORE)
  toolchains  <root>/toolchains/<version>/<profile>/  provisioned profiles (DEV_PLATFORM_TOOLCHAINS)
  cache       ${XDG_CACHE_HOME:-~/.cache}/dev-platform, or <root>/cache when the root is explicit or job-local
              (DEV_PLATFORM_CACHE). Nothing in the cache is trusted: every use re-checks it against the pins.
Nothing here needs elevated privileges or a global writable directory.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dev_platform.errors import ConfigError

HOME_ENV = "DEV_PLATFORM_HOME"
STORE_ENV = "DEV_PLATFORM_STORE"
TOOLCHAINS_ENV = "DEV_PLATFORM_TOOLCHAINS"
CACHE_ENV = "DEV_PLATFORM_CACHE"


def in_ci(env=os.environ) -> bool:
    return env.get("CI", "").lower() in ("1", "true") or env.get("GITHUB_ACTIONS") == "true"


@dataclass(frozen=True)
class Locations:
    store: Path
    toolchains: Path
    cache: Path
    scope: str  # "user" | "job" | "explicit": where the data root came from
    chosen_by: dict[str, str]  # location -> the flag, variable or default that chose it

    def toolchain_dir(self, version: str, profile: str) -> Path:
        return self.toolchains / version / profile


def data_root(env=os.environ, home: Path | None = None) -> tuple[Path, str, str]:
    """(root, scope, chosen_by)."""
    if home:
        return Path(home), "explicit", "--home"
    if env.get(HOME_ENV):
        return Path(env[HOME_ENV]), "explicit", HOME_ENV
    if in_ci(env):
        if not env.get("RUNNER_TEMP"):
            raise ConfigError(
                [
                    "in CI the default location is job-local ($RUNNER_TEMP/dev-platform) and RUNNER_TEMP is "
                    f"not set: pass --home or set {HOME_ENV}"
                ]
            )
        return Path(env["RUNNER_TEMP"]) / "dev-platform", "job", "RUNNER_TEMP (CI)"
    base = env.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "dev-platform", "user", "XDG_DATA_HOME" if env.get("XDG_DATA_HOME") else "default"


def locate(
    env=os.environ,
    *,
    home: Path | None = None,
    store: Path | None = None,
    toolchains: Path | None = None,
    cache: Path | None = None,
) -> Locations:
    chosen: dict[str, str] = {}

    def pick(name: str, flag: Path | None, var: str, default) -> Path:
        if flag:
            chosen[name] = f"--{name}"
            return Path(flag)
        if env.get(var):
            chosen[name] = var
            return Path(env[var])
        path, why = default()
        chosen[name] = why
        return path

    root: tuple[Path, str, str] | None = None

    def under(sub: str):
        def f():
            nonlocal root
            root = root or data_root(env, home)
            return root[0] / sub, root[2]

        return f

    def cache_default():
        nonlocal root
        root = root or data_root(env, home)
        if root[1] != "user":
            return root[0] / "cache", root[2]
        if env.get("XDG_CACHE_HOME"):
            return Path(env["XDG_CACHE_HOME"]) / "dev-platform", "XDG_CACHE_HOME"
        return Path.home() / ".cache" / "dev-platform", "default"

    s = pick("store", store, STORE_ENV, under("versions"))
    t = pick("toolchains", toolchains, TOOLCHAINS_ENV, under("toolchains"))
    c = pick("cache", cache, CACHE_ENV, cache_default)
    scope = root[1] if root else "explicit"  # the data root is consulted only when a location defaults to it
    return Locations(s.absolute(), t.absolute(), c.absolute(), scope, chosen)
