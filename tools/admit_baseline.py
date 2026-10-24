#!/usr/bin/env python3
"""Author the Bazel Rust/Python baseline profiles of toolchains/manifest.json from upstream publications.

Admission is a reviewed change: this prints (or with --write applies) the profiles for the candidate versions
below, taking every url and hash from the publisher (Rust channel manifest, python-build-standalone SHA256SUMS,
ruff and Bazel release checksums, Bazel Central Registry source.json). It never invents a pin and refuses a
candidate whose artifacts are missing. Closure digests of the executed tools are not published anywhere: they
are measured (`dev-platform toolchain measure`) on each supported platform and passed back with --closures;
without them a closure keeps its previous value, or a zero placeholder that fails verification.

    python3 tools/admit_baseline.py                      # print the profiles
    python3 tools/admit_baseline.py --write              # update toolchains/manifest.json
    python3 tools/admit_baseline.py --write --closures measured.json
        measured.json: {"<tool>@<version>": {"darwin-arm64": "<sha256>", "linux-x86_64": "<sha256>"}}
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tarfile
import tomllib
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "toolchains" / "manifest.json"
LOCK = ROOT / "src" / "dev_platform" / "bazel" / "python_lock.txt"

VERSIONS = {
    "rust": "1.99.1",
    "python": "3.15.1",
    "python_build": "20261021",  # python-build-standalone release carrying CPython 3.15.1
    "bazel": "9.3.1",
    "bazelisk": "1.30.0",
    "rules_rust": "0.74.0",
    "rules_python": "2.4.5",
    "ruff": "0.17.2",
    "edition": "2024",
}
PLATFORMS = {
    "darwin-arm64": {"triple": "aarch64-apple-darwin", "bazel": "darwin-arm64", "bazelisk": "darwin-arm64"},
    "linux-x86_64": {
        "triple": "x86_64-unknown-linux-gnu",
        "bazel": "linux-x86_64",
        "bazelisk": "linux-amd64",
    },
}
SYSTEM_LIBS = [
    "/usr/lib/",
    "/System/Library/",
    "ld-linux-x86-64.so.2",
    "libc.so.6",
    "libdl.so.2",
    "libm.so.6",
    "libpthread.so.0",
    "librt.so.1",
    "libutil.so.1",
    "libgcc_s.so.1",
]
# profile -> (languages, profile whose measured host-tool closures it shares). A published profile is never
# changed; the Python profiles' type checker is Ty.
PROFILES = {
    "rust-bazel-9.3": (("rust",), None),
    "python-ty-bazel-9.3": (("python",), None),
    "rust-python-ty-bazel-9.3": (("rust", "python"), None),
    "rust-aarch64-none-bazel-9.3": (("rust",), "rust-bazel-9.3"),
    "rust-python-ty-aarch64-none-bazel-9.3": (("rust", "python"), "rust-python-ty-bazel-9.3"),
}
# Additional Rust target triples a profile cross-compiles for (the host-installed toolchain is unchanged: the
# target's rust-std is pinned for Bazel only).
TARGETS = {
    "rust-aarch64-none-bazel-9.3": ["aarch64-unknown-none-softfloat"],
    "rust-python-ty-aarch64-none-bazel-9.3": ["aarch64-unknown-none-softfloat"],
}
ZERO = "0" * 64


def get(url: str) -> bytes:
    if not url.startswith("https://"):
        raise SystemExit(f"refusing non-https {url}")
    try:
        with urllib.request.urlopen(url, timeout=300) as r:
            return r.read()
    except OSError as e:
        raise SystemExit(f"cannot fetch {url}: {e}") from None


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def rust_components(version: str) -> dict[str, list[dict]]:
    """Per platform key: the component archives (name, url, sha256, install dirs) from the signed-by-https channel."""
    doc = tomllib.loads(get(f"https://static.rust-lang.org/dist/channel-rust-{version}.toml").decode())
    pkg = doc["pkg"]
    out: dict[str, list[dict]] = {}
    for key, p in PLATFORMS.items():
        t = p["triple"]
        # (dist package, directory name inside the archive, host-installed?)
        wanted = [
            ("rustc", "rustc", True),
            ("rust-std", f"rust-std-{t}", True),
            ("clippy-preview", "clippy-preview", True),
            ("rustfmt-preview", "rustfmt-preview", True),
            ("rust-analyzer-preview", "rust-analyzer-preview", True),
            ("rust-src", "rust-src", True),
            ("cargo", "cargo", False),
            ("llvm-tools-preview", "llvm-tools-preview", False),
        ]
        omit = {  # Cargo plugin shims: the host toolchain has no Cargo interface
            "clippy-preview": ["bin/cargo-clippy"],
            "rustfmt-preview": ["bin/cargo-fmt"],
        }
        comps = []
        for name, install, host in wanted:
            tgt = pkg[name]["target"]
            e = tgt.get(t) or tgt.get("*")
            if not e or not e.get("available"):
                raise SystemExit(f"rust {version}: {name} is not available for {t}")
            c = {"archive": e["xz_url"].rsplit("/", 1)[1], "url": e["xz_url"], "sha256": e["xz_hash"]}
            if host:
                comps.append({**c, "install": [install], **({"omit": omit[name]} if name in omit else {})})
            else:
                comps.append({**c, "bazel_only": True})
        out[key] = comps
    return out


def target_std(version: str, triple: str) -> dict[str, dict]:
    """Per platform key: the rust-std archive of an extra target, pinned for Bazel only (nothing is installed on
    the host)."""
    pkg = tomllib.loads(get(f"https://static.rust-lang.org/dist/channel-rust-{version}.toml").decode())[
        "pkg"
    ]["rust-std"]["target"].get(triple)
    if not pkg or not pkg.get("available"):
        raise SystemExit(f"rust {version}: rust-std is not available for {triple}")
    comp = {"archive": pkg["xz_url"].rsplit("/", 1)[1], "url": pkg["xz_url"], "sha256": pkg["xz_hash"]}
    return {k: {"type": "rust-components", "components": [{**comp, "bazel_only": True}]} for k in PLATFORMS}


def python_sources(version: str, build: str) -> dict[str, dict]:
    base = f"https://github.com/astral-sh/python-build-standalone/releases/download/{build}"
    sums = {}
    for line in get(f"{base}/SHA256SUMS").decode().splitlines():
        h, _, name = line.partition("  ")
        sums[name.strip()] = h
    out = {}
    for key, p in PLATFORMS.items():
        name = f"cpython-{version}+{build}-{p['triple']}-install_only_stripped.tar.gz"
        if name not in sums:
            raise SystemExit(f"python-build-standalone {build}: {name} not published")
        out[key] = {"url": f"{base}/{name.replace('+', '%2B')}", "sha256": sums[name], "strip": "python"}
    return out


def ruff_sources_and_binary(version: str) -> tuple[dict[str, dict], dict[str, str]]:
    """Archive pins from the release's checksum files; the executable's own sha256 (its closure) from the archive."""
    base = f"https://github.com/astral-sh/ruff/releases/download/{version}"
    srcs, binary = {}, {}
    for key, p in PLATFORMS.items():
        top = f"ruff-{p['triple']}"
        data = get(f"{base}/{top}.tar.gz")
        want = get(f"{base}/{top}.tar.gz.sha256").decode().split()[0]
        if sha(data) != want:
            raise SystemExit(f"ruff {version}: {top}.tar.gz does not match its published checksum")
        srcs[key] = {"url": f"{base}/{top}.tar.gz", "sha256": want, "strip": top, "into": "bin"}
        with tarfile.open(fileobj=__import__("io").BytesIO(data), mode="r:gz") as tar:
            f = tar.extractfile(f"{top}/ruff")
            assert f is not None
            binary[key] = sha(f.read())
    return srcs, binary


def bazel_pins(version: str, bazelisk: str) -> tuple[dict, dict]:
    bz, bl = {}, {}
    for key, p in PLATFORMS.items():
        text = get(
            f"https://github.com/bazelbuild/bazel/releases/download/{version}/bazel-{version}-{p['bazel']}.sha256"
        )
        bz[key] = text.decode().split()[0]
        url = f"https://github.com/bazelbuild/bazelisk/releases/download/v{bazelisk}/bazelisk-{p['bazelisk']}"
        bl[key] = {"url": url, "sha256": sha(get(url)), "type": "binary", "as": "bazel"}
    return bz, bl


def module_pin(name: str, version: str) -> dict:
    url = f"https://bcr.bazel.build/modules/{name}/{version}/source.json"
    return {"kind": "bazel_module", "name": name, "version": version, "source_json_sha256": sha(get(url))}


def locked_versions() -> dict[str, str]:
    text = LOCK.read_text()
    return {n: v for n, v in re.findall(r"^([a-z][a-z0-9_.-]*)==(\S+)", text, re.M)}


def file_closure(sha_by_key: dict[str, str]) -> dict:
    return {"kind": "file", "sha256": dict(sha_by_key), "system_libs": SYSTEM_LIBS}


def measured(tool: str, version: str, prior: dict, measures: dict) -> dict[str, str]:
    got = dict(prior.get("closure", {}).get("sha256", {}))
    got.update(measures.get(f"{tool}@{version}", {}))
    return {k: got.get(k, ZERO) for k in PLATFORMS}


def build(prior: dict, measures: dict) -> dict:
    v = VERSIONS
    rust = rust_components(v["rust"])
    py = python_sources(v["python"], v["python_build"])
    ruff_src, ruff_bin = ruff_sources_and_binary(v["ruff"])
    bz, bl = bazel_pins(v["bazel"], v["bazelisk"])
    mods = {n: module_pin(n, v[n]) for n in ("rules_rust", "rules_python")}
    module_file = "dev-platform/toolchains.MODULE.bazel"
    old = prior.get("profiles", {})

    def prev(profile: str, tool: str) -> dict:
        sibling = PROFILES[profile][1]
        found = old.get(profile, {}).get("tools", {}).get(tool, {})
        return found or old.get(sibling, {}).get("tools", {}).get(tool, {})

    def tools_for(profile: str, langs: tuple[str, ...]) -> dict:
        locked = locked_versions()
        lock_file = "dev-platform/python_lock.txt"
        t: dict = {
            "bazelisk": {
                "version": v["bazelisk"],
                "executable": "bazel",
                "purl": f"pkg:github/bazelbuild/bazelisk@v{v['bazelisk']}",
                "closure": file_closure({k: bl[k]["sha256"] for k in PLATFORMS}),
                "source": bl,
            },
            "bazel": {
                "version": v["bazel"],
                "bazel_managed": True,
                "declared_in": {"file": ".bazelversion", "pattern": r"(\S+)"},
                "launcher": "bazelisk",
                "binary_sha256": bz,
                "purl": f"pkg:github/bazelbuild/bazel@{v['bazel']}",
            },
        }
        if "rust" in langs:
            rv = v["rust"]
            for triple in TARGETS.get(profile, ()):
                t[f"rust-std-{triple}"] = {
                    "version": rv,
                    "bazel_managed": True,
                    "bound_to": "bazel-config",
                    "declared_in": {
                        "file": module_file,
                        "pattern": rf'"rust-std-([0-9.]+)-{re.escape(triple)}\.tar\.xz"',
                    },
                    "purl": f"pkg:generic/rust-std@{rv}?target={triple}",
                    "source": target_std(rv, triple),
                }
            t["rust-toolchain"] = {
                "version": rv,
                "bazel_managed": True,
                "declared_in": {"file": module_file, "pattern": r'versions = \["([^"]+)"\]'},
                "integrity": [{**mods["rules_rust"], "file": module_file}],
                "purl": f"pkg:generic/rust@{rv}",
            }
            t["rust-dev"] = {
                "version": rv,
                "executable": "rustc",
                "purl": f"pkg:generic/rust@{rv}",
                "closure": {
                    "kind": "prefix",
                    "prefix_up": 2,
                    "sha256": measured("rust-dev", rv, prev(profile, "rust-dev"), measures),
                    "system_libs": [*SYSTEM_LIBS, "libz.so.1"],
                },
                "source": {k: {"type": "rust-components", "components": rust[k]} for k in PLATFORMS},
            }
        if "python" in langs:
            pv = v["python"]
            t["python"] = {
                "version": pv,
                "executable": "{python}",
                "probe": {"argv": ["{python}", "--version"], "pattern": r"Python (\S+)"},
                "purl": f"pkg:generic/cpython@{pv}",
                "closure": {
                    "kind": "prefix",
                    "prefix_up": 2,
                    "sha256": measured("python", pv, prev(profile, "python"), measures),
                    "system_libs": SYSTEM_LIBS,
                },
                "source": py,
            }
            t["python-runtime"] = {
                "version": pv,
                "bazel_managed": True,
                "declared_in": {"file": module_file, "pattern": r'python_version = "([^"]+)"'},
                "integrity": [{**mods["rules_python"], "file": module_file}],
                "purl": f"pkg:generic/cpython@{pv}",
            }
            t["ruff"] = {
                "version": v["ruff"],
                "executable": "ruff",
                "probe": {"argv": ["ruff", "--version"], "pattern": r"ruff (\S+)"},
                "purl": f"pkg:pypi/ruff@{v['ruff']}",
                "closure": file_closure(ruff_bin),
                "source": ruff_src,
            }
            for name in ("pytest", "pytest-cov", "coverage", "ty"):
                t[name] = {
                    "version": locked[name],
                    "bazel_managed": True,
                    "bound_to": "bazel-config",
                    "declared_in": {"file": lock_file, "pattern": rf"(?m)^{re.escape(name)}==(\S+)"},
                    "purl": f"pkg:pypi/{name}@{locked[name]}",
                }
        return dict(sorted(t.items()))

    profiles = {}
    for name, (langs, _) in PROFILES.items():
        bazel = {"edition": v["edition"]} if "rust" in langs else {}
        if name in TARGETS:
            bazel["extra_target_triples"] = TARGETS[name]
        profiles[name] = {"tools": tools_for(name, langs), "bazel": bazel}
    return profiles


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    ap.add_argument("--write", action="store_true", help="update toolchains/manifest.json in place")
    ap.add_argument("--closures", type=Path, help="measured closure digests (JSON, see the module docstring)")
    a = ap.parse_args(argv)
    prior = json.loads(MANIFEST.read_text())
    measures = json.loads(a.closures.read_text()) if a.closures else {}
    profiles = build(prior, measures)
    if not a.write:
        print(json.dumps(profiles, indent=2))
        return 0
    prior["profiles"].update(profiles)
    MANIFEST.write_text(json.dumps(prior, indent=2) + "\n")
    print(f"wrote {sorted(profiles)} to {MANIFEST}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
