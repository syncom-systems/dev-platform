"""Verified Bazel execution for a project that stays its own root module (ADR 0028, Design C; experimental).

The project keeps its `MODULE.bazel`, `.bazelrc` and committed `MODULE.bazel.lock`; nothing is written into
it. The platform supplies, from outside the repository:

1. **its verified rules_rust** (`--override_module=rules_rust=<overlay>`): the release's pinned rules_rust
   source (BCR `source.json` by the manifest's hash, the archive by the integrity that file names),
   re-derived on every run into the cache with the platform's changes: the Rust toolchain declared in
   rules_rust's own `MODULE.bazel` (the release's version, sha256s and extra targets), a root
   `rust.toolchain` that differs from it fails closed, and the policy package `@@rules_rust+//dev_platform`
   (rustfmt.toml, clippy.toml, the cross-compilation platforms);
2. **the effective arguments**: project `.bazelrc` files (with their imports) and the command line are
   scanned and refused when they name an option that could replace a platform-owned module, repository or
   toolchain; the launcher's own options come last (`--extra_toolchains` puts the platform's toolchains
   first, the lint policy settings win over any earlier value), `--lockfile_mode=error` verifies the
   committed lock without writing it, user and system rc files are not read, and Bazelisk is held to the
   release's Bazel version and binary digest with the project's `tools/bazel` wrapper skipped;
3. **evidence**: `lint` proves from the Build Event Protocol that clippy and rustfmt produced a result for
   every applicable Rust target (or names why not), `--audit` checks the version of every rustc the actions
   name, and `--record` writes the run record. Only a run whose record says `verified: true` is verified Dev
   Platform execution; plain `bazel` in the same repository is the project's own and never is.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import tomllib
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from dev_platform import bazelconf, provision
from dev_platform import digest as _digest
from dev_platform.errors import EXIT_OK, EXIT_UNSATISFIED, ConfigError

SCHEMA = "dev-platform.bazel-run/v1"
BCR = "https://bcr.bazel.build"
RULES_RUST = "rules_rust"
RULES_RUST_REPO = "@@rules_rust+"
TOOLCHAINS = "@@rules_rust++rust+rust_toolchains//:all"
TOOLCHAIN_REPO_PREFIX = "rules_rust++rust+"
POLICY_PKG = "dev_platform"
LOCKFILE = "MODULE.bazel.lock"
ASPECTS = (
    f"{RULES_RUST_REPO}//rust:defs.bzl%rustfmt_aspect",
    f"{RULES_RUST_REPO}//rust:defs.bzl%rust_clippy_aspect",
)
LINT_GROUPS = ("clippy_checks", "rustfmt_checks")
LINTED_KINDS = {
    "rust_binary",
    "rust_library",
    "rust_proc_macro",
    "rust_shared_library",
    "rust_static_library",
    "rust_test",
}
# rules_rust 0.74.0 rust/private/clippy.bzl and rustfmt.bzl: targets with these tags are skipped by design
OPT_OUT = {
    "clippy_checks": {"no_clippy", "no_lint", "nolint", "noclippy"},
    "rustfmt_checks": {"no_format", "no_rustfmt", "norustfmt"},
}
BUILD_COMMANDS = ("build", "test", "coverage", "run", "cquery", "aquery", "info")
LOADING_COMMANDS = ("query",)
COMMANDS = (*BUILD_COMMANDS, *LOADING_COMMANDS, "lint")

DENIED = {
    "override_repository": "replaces an external repository, including the platform's toolchain repositories",
    "override_module": "replaces a Bazel module, including the platform's rules_rust",
    "inject_repository": "adds repositories to a module extension's scope",
    "extra_toolchains": "registers toolchains ahead of the platform's",
    "registry": "changes where Bazel modules are resolved from",
    "lockfile_mode": "the launcher verifies the committed MODULE.bazel.lock (error mode), never updates it",
    "vendor_dir": "vendored repositories replace the fetched, verified ones",
    "repository_cache": "the repository cache is chosen by the launcher's environment, not the project",
    "distdir": "distdir archives replace downloads",
}
# boolean options refused only with one value: name -> (refused value, reason)
DENIED_VALUE = {
    "enable_bzlmod": (False, "the platform's toolchains are delivered through Bzlmod"),
    "enable_workspace": (True, "WORKSPACE repositories bypass the module graph the lockfile verifies"),
}
_TRUE, _FALSE = {"", "1", "true", "yes"}, {"0", "false", "no"}
_TOOLCHAIN_SETTING = re.compile(r"^@@?rules_rust\+?//rust/toolchain")
_SRI = re.compile(r"^sha256-([A-Za-z0-9+/=]+)$")

_ANCHOR_TAG = 'rust.toolchain(edition = "2021")\n'
_ANCHOR_TOOLCHAINS = "    toolchains = root.tags.toolchain or rules_rust.tags.toolchain\n"
_ANCHOR_EDITION = "                edition = toolchain.edition,\n"

Run = Callable[..., subprocess.CompletedProcess]


def _run(argv: list[str], *, cwd: Path, env: dict, capture: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(argv, cwd=cwd, env=env, capture_output=capture, text=True, check=False)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ------------------------------------------------------------------------------------------- argument policy


def option_name(arg: str) -> str | None:
    """`--name=value`, `--name` or `--noname` -> `name` / `noname`; label flags keep their label."""
    if not arg.startswith("--") or len(arg) == 2:
        return None
    return arg[2:].split("=", 1)[0]


def refusal(arg: str) -> str | None:
    """Why an option is not allowed in a verified run (None: allowed)."""
    name = option_name(arg)
    if name is None:
        return None
    negated = name.startswith("no") and (name[2:] in DENIED or name[2:] in DENIED_VALUE)
    base = name[2:] if negated else name
    if base in DENIED:
        return DENIED[base]
    if base in DENIED_VALUE:
        value = arg.split("=", 1)[1].lower() if "=" in arg else ""
        on = False if negated else (True if value in _TRUE else (False if value in _FALSE else None))
        refused, why = DENIED_VALUE[base]
        return why if on is None or on == refused else None
    if _TOOLCHAIN_SETTING.match(name):
        return "a rules_rust toolchain setting changes which toolchain matches"
    return None


def _logical_lines(text: str) -> Iterable[tuple[int, str]]:
    """Lines of an rc file with backslash continuations joined, numbered by their first physical line."""
    buf, start = "", 0
    for n, line in enumerate(text.splitlines(), 1):
        if not buf:
            start = n
        if line.endswith("\\"):
            buf += line[:-1] + " "
            continue
        yield start, buf + line
        buf = ""
    if buf:
        yield start, buf


def scan_rc(project: Path) -> tuple[list[str], list[dict]]:
    """(rc files read, findings) for the project's `.bazelrc` and every file it imports. Every section and
    config counts: a denied option under `build:anything` is refused like one under `common`."""
    project = Path(project)
    files: list[str] = []
    findings: list[dict] = []
    seen: set[Path] = set()

    def visit(path: Path) -> None:
        real = path.resolve()
        if real in seen or not real.is_file():
            return
        seen.add(real)
        files.append(str(real))
        for n, line in _logical_lines(real.read_text(errors="replace")):
            try:
                toks = shlex.split(line, comments=True)
            except ValueError:
                findings.append(
                    {"file": str(real), "line": n, "option": line.strip(), "reason": "unparseable"}
                )
                continue
            if not toks:
                continue
            if toks[0] in ("import", "try-import"):
                if len(toks) > 1:
                    target = Path(toks[1].replace("%workspace%", str(project)))
                    visit(target if target.is_absolute() else project / target)
                continue
            for tok in toks[1:]:
                if why := refusal(tok):
                    findings.append({"file": str(real), "line": n, "option": tok, "reason": why})

    visit(project / ".bazelrc")
    return files, findings


def scan_args(args: list[str]) -> list[dict]:
    """Refusals among the user's options (before `--`; after it come target patterns, or for `run` the
    program's own arguments)."""
    pre, _ = split_args(args)
    return [{"argument": a, "reason": why} for a in pre if (why := refusal(a))]


def split_args(args: list[str]) -> tuple[list[str], list[str] | None]:
    if "--" in args:
        i = args.index("--")
        return args[:i], args[i + 1 :]
    return list(args), None


def patterns(args: list[str]) -> list[str]:
    """Positive target patterns among the arguments (negative `-//x` patterns are left out: a superset)."""
    pre, post = split_args(args)
    return [a for a in [*pre, *(post or [])] if not a.startswith("-")]


# ---------------------------------------------------------------------------------------- rules_rust overlay


def rules_rust_pin(manifest: dict, profile: str) -> dict:
    tool = manifest["profiles"][profile]["tools"].get("rust-toolchain") or {}
    for ent in tool.get("integrity", []):
        if ent.get("kind") == "bazel_module" and ent.get("name") == RULES_RUST:
            return ent
    raise ConfigError([f"profile {profile!r} pins no rules_rust module (rust-toolchain.integrity)"])


def toolchain_tag(manifest: dict, profile: str) -> str:
    """The Rust toolchain declaration in the overlay's MODULE.bazel (the values of ADR 0025's rendering)."""
    prof = manifest["profiles"][profile]
    tools = prof["tools"]
    version = tools["rust-toolchain"]["version"]
    targets = bazelconf.extra_targets(prof)
    sha = bazelconf.rust_sha256s(tools["rust-dev"], *(tools[f"rust-std-{t}"] for t in targets))
    return (
        "rust.toolchain(\n"
        f'    edition = "{prof["bazel"].get("edition", "2021")}",\n'
        f"    extra_target_triples = {json.dumps(targets)},\n"
        f'    rustfmt_version = "{version}",\n'
        "    sha256s = {\n"
        f"{bazelconf._starlark_dict(sha)}\n"
        "    },\n"
        f'    versions = ["{version}"],\n'
        ")\n"
    )


def policy_files(manifest: dict, profile: str, release: str) -> dict[str, str]:
    """`dev_platform/` inside the overlay: formatter and lint policy and the cross-compilation platforms."""
    prof = manifest["profiles"][profile]
    version = prof["tools"]["rust-toolchain"]["version"]
    edition = prof["bazel"].get("edition", "")
    head = f"# dev-platform {release} for profile {profile} (ADR 0028): the verified rules_rust overlay\n"
    out = {
        f"{POLICY_PKG}/{name}": bazelconf._sub(
            bazelconf._template(name), RUST_VERSION=version, EDITION=edition
        )
        for name in bazelconf.RUST_POLICY
    }
    build = head + 'package(default_visibility = ["//visibility:public"])\n\n'
    build += f"exports_files({json.dumps(sorted(bazelconf.RUST_POLICY))})\n"
    for triple in bazelconf.extra_targets(prof):
        t = bazelconf.TARGETS[triple]
        build += (
            f'\nplatform(\n    name = "{t["platform"]}",\n'
            f'    constraint_values = ["@platforms//cpu:{t["cpu"]}", "@platforms//os:{t["os"]}"],\n)\n'
        )
    out[f"{POLICY_PKG}/BUILD.bazel"] = build
    return out


def _edit_once(text: str, anchor: str, replacement: str, where: str) -> str:
    n = text.count(anchor)
    if n != 1:
        raise ConfigError(
            [
                f"rules_rust {where}: expected exactly one {anchor.strip()!r}, found {n}; this rules_rust "
                "source is not the one the platform's overlay is qualified for"
            ]
        )
    return text.replace(anchor, replacement)


def derive(src: Path, manifest: dict, profile: str, release: str) -> None:
    """Apply the platform's changes to an extracted rules_rust tree, in place."""
    mod = src / "MODULE.bazel"
    mod.write_text(
        _edit_once(
            mod.read_text(),
            _ANCHOR_TAG,
            f"# dev-platform {release} ({profile}): the verified Rust toolchain (ADR 0028)\n"
            + toolchain_tag(manifest, profile),
            "MODULE.bazel",
        )
    )
    ext = src / "rust" / "extensions.bzl"
    frag = bazelconf._sub(bazelconf._template("rules_rust_enforce.bzl.frag"), RELEASE=release)
    text = _edit_once(ext.read_text(), _ANCHOR_TOOLCHAINS, frag, "rust/extensions.bzl")
    text = _edit_once(
        text,
        _ANCHOR_EDITION,
        "                edition = root_edition or toolchain.edition,\n",
        "rust/extensions.bzl",
    )
    ext.write_text(text)
    for rel, body in policy_files(manifest, profile, release).items():
        p = src / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)


@dataclass(frozen=True)
class Overlay:
    path: Path
    digest: str
    version: str
    archive_sha256: str
    source_json_sha256: str
    repaired: bool

    def record(self) -> dict:
        return {
            "path": str(self.path),
            "tree_digest": self.digest,
            "rules_rust": self.version,
            "archive_sha256": self.archive_sha256,
            "source_json_sha256": self.source_json_sha256,
            "repaired": self.repaired,
        }


def _sri_hex(integrity: str) -> str:
    m = _SRI.match(integrity or "")
    if not m:
        raise ConfigError(
            [f"rules_rust source.json: unsupported integrity {integrity!r} (sha256 SRI required)"]
        )
    return base64.b64decode(m.group(1)).hex()


def ensure_overlay(
    manifest: dict,
    profile: str,
    release: str,
    cache: Path,
    *,
    fetch: Callable[[str, str, Path], None] = provision.fetch,
) -> Overlay:
    """The verified rules_rust tree under `cache`, re-derived from the pinned sources on every call: the
    cache is not trusted, so a cached tree is used only when it equals a fresh derivation, and replaced
    otherwise."""
    pin = rules_rust_pin(manifest, profile)
    version, sj_sha = pin["version"], pin["source_json_sha256"]
    base = Path(cache) / "bazel"
    dl = base / "downloads"
    dl.mkdir(parents=True, exist_ok=True)
    sj = dl / f"rules_rust-{version}.source.json"
    if not (sj.is_file() and _sha256(sj) == sj_sha):
        fetch(f"{BCR}/modules/{RULES_RUST}/{version}/source.json", sj_sha, sj)
    source = json.loads(sj.read_text())
    extra = sorted(set(source) - {"integrity", "strip_prefix", "url"})
    if extra:
        raise ConfigError([f"rules_rust {version} source.json uses {extra}: not supported by the overlay"])
    arc_sha = _sri_hex(source.get("integrity", ""))
    arc = dl / f"rules_rust-{version}-{arc_sha[:16]}.tar.gz"
    if not (arc.is_file() and _sha256(arc) == arc_sha):
        fetch(source["url"], arc_sha, arc)
    with tempfile.TemporaryDirectory(prefix="rules_rust-", dir=base) as td:
        fresh = Path(td) / "tree"
        fresh.mkdir()
        provision.extract(arc, fresh, source.get("strip_prefix", ""))
        derive(fresh, manifest, profile, release)
        want = _digest.tree_digest(fresh)
        final = base / f"rules_rust-{version}-{want[:16]}"
        repaired = False
        if final.exists():
            try:
                if _digest.tree_digest(final) == want:
                    return Overlay(final, want, version, arc_sha, sj_sha, False)
            except (ValueError, OSError):
                pass
            shutil.rmtree(final)
            repaired = True
        fresh.rename(final)
    return Overlay(final, want, version, arc_sha, sj_sha, repaired)


def platform_rc(manifest: dict, profile: str, release: str, cache: Path) -> Path:
    """The platform's rc file (read after the project's): configuration names the platform defines."""
    prof = manifest["profiles"][profile]
    text = f"# dev-platform {release} for profile {profile} (ADR 0028)\ncoverage --combined_report=lcov\n"
    for triple in bazelconf.extra_targets(prof):
        t = bazelconf.TARGETS[triple]
        text += f"build:{t['config']} --platforms={RULES_RUST_REPO}//{POLICY_PKG}:{t['platform']}\n"
    path = Path(cache) / "bazel" / f"platform-{hashlib.sha256(text.encode()).hexdigest()[:16]}.bazelrc"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.is_file() or path.read_text() != text:
        path.write_text(text)
    return path


# --------------------------------------------------------------------------------------- effective arguments


def policy_flags() -> list[str]:
    return [
        f"--{RULES_RUST_REPO}//rust/settings:rustfmt.toml={RULES_RUST_REPO}//{POLICY_PKG}:rustfmt.toml",
        f"--{RULES_RUST_REPO}//rust/settings:clippy.toml={RULES_RUST_REPO}//{POLICY_PKG}:clippy.toml",
        f"--{RULES_RUST_REPO}//rust/settings:clippy_flags=-D,warnings",
    ]


@dataclass(frozen=True)
class Places:
    """Where Bazel keeps its state, chosen by the launcher's caller (never by the project): None is Bazel's
    default. The repository cache also holds repository contents Bazel reuses without re-verifying them."""

    output_user_root: Path | None = None
    repository_cache: Path | None = None


DEFAULT_PLACES = Places()


def startup_flags(rc: Path, places: Places = DEFAULT_PLACES) -> list[str]:
    out = ["--nohome_rc", "--nosystem_rc", f"--bazelrc={rc}"]
    if places.output_user_root:
        out.append(f"--output_user_root={places.output_user_root}")
    return out


def enforced_flags(
    command: str, overlay: Path, *, bep: Path | None = None, places: Places = DEFAULT_PLACES
) -> list[str]:
    """The launcher's options, placed after the user's so that each wins over any earlier value."""
    tail = [f"--override_module={RULES_RUST}={overlay}", "--lockfile_mode=error"]
    if places.repository_cache:
        tail.append(f"--repository_cache={places.repository_cache}")
    if command in BUILD_COMMANDS or command == "lint":
        tail += [f"--extra_toolchains={TOOLCHAINS}", *policy_flags()]
    if command == "lint":
        tail += [f"--aspects={','.join(ASPECTS)}", f"--output_groups={','.join(sorted(LINT_GROUPS))}"]
    if bep is not None:
        tail.append(f"--build_event_json_file={bep}")
    return tail


def argv(
    bazel: str,
    command: str,
    args: list[str],
    overlay: Path,
    rc: Path,
    *,
    bep: Path | None = None,
    places: Places = DEFAULT_PLACES,
) -> list[str]:
    pre, post = split_args(args)
    verb = "build" if command == "lint" else command
    tail = enforced_flags(command, overlay, bep=bep, places=places)
    out = [bazel, *startup_flags(rc, places), verb, *pre, *tail]
    return out + (["--", *post] if post is not None else [])


def bazel_env(manifest: dict, profile: str, base: dict | None = None) -> dict[str, str]:
    """Bazelisk runs the release's Bazel version and verifies its binary digest; the project's
    `tools/bazel` wrapper (which could rewrite the arguments) is skipped. These override `.bazelversion`
    and `.bazeliskrc`."""
    from dev_platform.toolchain import runtime_env

    env = dict(os.environ if base is None else base)
    env.update(runtime_env(manifest, profile))
    env["USE_BAZEL_VERSION"] = manifest["profiles"][profile]["tools"]["bazel"]["version"]
    env["BAZELISK_SKIP_WRAPPER"] = "true"
    return env


# --------------------------------------------------------------------------------------------- lint evidence


def lint_outcome(bep_lines: Iterable[str]) -> dict:
    """Per applicable Rust target and lint group: `checked` (a result file), `skipped` (not built in this
    configuration), `opted-out` (a rules_rust skip tag), `failed`, `not-run`, or `empty` (completed with no
    result: allowed for rustfmt only for a target without a hand-written source, which the caller checks)."""
    sets: dict[str, dict] = {}
    kinds: dict[str, str] = {}
    tags: dict[str, set[str]] = defaultdict(set)
    skipped: set[str] = set()
    groups: dict[tuple[str, str], list[str]] = defaultdict(list)
    done: dict[tuple[str, str], bool] = {}
    for line in bep_lines:
        if not line.strip():
            continue
        e = json.loads(line)
        i = e.get("id", {})
        if "namedSet" in i:
            sets[i["namedSet"]["id"]] = e.get("namedSetOfFiles", {})
        elif "targetConfigured" in i and "aspect" not in i["targetConfigured"]:
            label = i["targetConfigured"]["label"]
            conf = e.get("configured", {})
            kinds[label] = (conf.get("targetKind") or "").removesuffix(" rule")
            tags[label] |= set(conf.get("tag") or [])
        elif "targetCompleted" in i:
            label, aspect = i["targetCompleted"]["label"], i["targetCompleted"].get("aspect", "")
            if not aspect:
                if e.get("aborted", {}).get("reason") == "SKIPPED":
                    skipped.add(label)
                tags[label] |= set(e.get("completed", {}).get("tag") or [])
                continue
            group = (
                "clippy_checks"
                if aspect.endswith("%rust_clippy_aspect")
                else ("rustfmt_checks" if aspect.endswith("%rustfmt_aspect") else None)
            )
            if group is None:
                continue
            done[(label, group)] = bool(e.get("completed", {}).get("success"))
            for g in e.get("completed", {}).get("outputGroup", []):
                if g.get("name") == group:
                    groups[(label, group)] += [f["id"] for f in g.get("fileSets", [])]

    def count(ids: list[str], seen: set[str]) -> int:
        n = 0
        for x in ids:
            if x in seen:
                continue
            seen.add(x)
            s = sets.get(x, {})
            n += len(s.get("files", [])) + count([y["id"] for y in s.get("fileSets", [])], seen)
        return n

    targets: dict[str, dict] = {}
    for label, kind in sorted(kinds.items()):
        if kind not in LINTED_KINDS:
            continue
        row = {"kind": kind}
        for group in LINT_GROUPS:
            if label in skipped:
                row[group] = "skipped"
            elif tags[label] & OPT_OUT[group]:
                row[group] = "opted-out"
            elif count(groups.get((label, group), []), set()):
                row[group] = "checked"
            elif (label, group) not in done:
                row[group] = "not-run"  # the build stopped before this check (without --keep_going)
            elif done[(label, group)] is False:
                row[group] = "failed"
            else:
                row[group] = "empty"
        targets[label] = row
    return {"targets": targets}


def lint_problems(outcome: dict, has_sources: Callable[[str], bool]) -> list[str]:
    """What makes a lint run unacceptable: no Rust target checked at all, or a target neither checked nor
    accounted for (skipped, opted out, failed, or for rustfmt only, without a hand-written source)."""
    problems = []
    rows = outcome["targets"]
    for group in LINT_GROUPS:
        if not any(r[group] == "checked" for r in rows.values()):
            problems.append(
                f"{group}: no applicable Rust target was checked (a lint run that checks nothing fails)"
            )
    for label, r in rows.items():
        for group in LINT_GROUPS:
            if r[group] != "empty":
                continue
            if group == "rustfmt_checks" and not has_sources(label):
                r[group] = "no-source"
            else:
                r[group] = "unchecked"
                problems.append(f"{label}: {group} completed without a result and without a recorded reason")
    return problems


def lint_summary(outcome: dict) -> dict:
    out = {}
    for group in LINT_GROUPS:
        c: dict[str, int] = defaultdict(int)
        for r in outcome["targets"].values():
            c[r[group]] += 1
        out[group] = dict(sorted(c.items()))
    return out


# -------------------------------------------------------------------------------------------- compiler audit


def audit_rustc(
    query: Callable[[list[str]], subprocess.CompletedProcess],
    targets: list[str],
    option_args: list[str],
    want: str,
    *,
    run_rustc: Callable[[Path], str] | None = None,
) -> dict:
    """Every rustc the Rustc actions of `targets` name must come from the platform's toolchain repositories
    and report the release's version. The version is read from the binary, not inferred from the repository
    name: a replaced repository keeps its name (#190, the repository-override finding)."""
    from dev_platform import bazel_rust

    def default_rustc(p: Path) -> str:
        if not p.is_file():
            return ""
        return subprocess.run([str(p), "--version"], capture_output=True, text=True, check=False).stdout

    run_rustc = run_rustc or default_rustc
    rec: dict = {"want": want, "rustc": [], "problems": []}
    expr = f'mnemonic("Rustc", deps(set({" ".join(targets)})))'
    aq = query(["aquery", expr, *option_args, "--output=jsonproto"])
    paths = bazel_rust.rustc_paths(aq.stdout) if aq.returncode == 0 else set()
    if not paths:
        rec["problems"].append(f"no Rustc action found for {targets} (aquery exit {aq.returncode})")
        return rec
    info = query(["info", *option_args, "execution_root"])
    root = Path(info.stdout.strip()) if info.returncode == 0 and info.stdout.strip() else None
    if root is None:
        rec["problems"].append("cannot determine the execution root")
        return rec
    for rel in sorted(paths):
        m = re.search(r"(?:^|/)external/([^/]+)/", rel)
        repo = m.group(1) if m else None
        real = Path(os.path.realpath(root / rel))
        out = run_rustc(real)
        vm = re.match(r"rustc (\S+)", out.strip())
        row = {"path": rel, "repository": repo, "version": vm.group(1) if vm else None}
        rec["rustc"].append(row)
        if not repo or not repo.startswith(TOOLCHAIN_REPO_PREFIX):
            rec["problems"].append(f"{rel}: not a platform toolchain repository")
        if row["version"] != want:
            rec["problems"].append(f"{rel}: rustc reports {row['version']}, the release pins {want}")
    return rec


# --------------------------------------------------------------------------------------------------- the run


def project_profile(project: Path) -> str | None:
    f = Path(project) / "dev-platform.toml"
    if not f.is_file():
        return None
    return (tomllib.loads(f.read_text()).get("platform") or {}).get("profile")


def execute(
    *,
    project: Path,
    command: str,
    args: list[str],
    manifest: dict,
    profile: str,
    release: str,
    cache: Path,
    bazel: str = "bazel",
    audit: bool = False,
    places: Places = DEFAULT_PLACES,
    run: Run = _run,
    fetch: Callable[[str, str, Path], None] = provision.fetch,
    base_env: dict | None = None,
) -> tuple[int, dict]:
    """(exit code, run record). Refusals raise ConfigError before Bazel runs."""
    project = Path(project).resolve()
    if command not in COMMANDS:
        raise ConfigError(
            [f"`dev-platform bazel {command}` is not supported (supported: {', '.join(COMMANDS)})"]
        )
    if profile not in manifest["profiles"] or "bazel" not in manifest["profiles"][profile]:
        raise ConfigError([f"profile {profile!r} has no Bazel configuration in this release's manifest"])
    if not (project / "MODULE.bazel").is_file():
        raise ConfigError([f"{project} has no MODULE.bazel: the project must be its own Bazel root module"])
    rc_files, rc_findings = scan_rc(project)
    arg_findings = scan_args(args)
    if rc_findings or arg_findings:
        lines = [f"{f['file']}:{f['line']}: {f['option']}: {f['reason']}" for f in rc_findings]
        lines += [f"argument {f['argument']}: {f['reason']}" for f in arg_findings]
        raise ConfigError(
            ["refused: these options could replace platform-owned modules or toolchains", *lines]
        )
    lock = project / LOCKFILE
    if not lock.is_file():
        raise ConfigError(
            [
                f"{project} has no committed {LOCKFILE}: the launcher verifies it read-only "
                "(--lockfile_mode=error); the project creates and updates it itself "
                "(bazel mod deps --lockfile_mode=update) and commits it"
            ]
        )
    lock_before = _sha256(lock)
    overlay = ensure_overlay(manifest, profile, release, cache, fetch=fetch)
    rc = platform_rc(manifest, profile, release, cache)
    env = bazel_env(manifest, profile, base_env)
    want_bazel = manifest["profiles"][profile]["tools"]["bazel"]["version"]
    ver = run([bazel, "--version"], cwd=project, env=env)
    got_bazel = (ver.stdout or "").strip().removeprefix("bazel ").strip()
    if ver.returncode != 0 or got_bazel != want_bazel:
        raise ConfigError(
            [f"{bazel} runs Bazel {got_bazel or '?'} (exit {ver.returncode}); the release pins {want_bazel}"]
        )
    problems: list[str] = []
    record: dict = {
        "schema": SCHEMA,
        "release": release,
        "profile": profile,
        "project": str(project),
        "command": command,
        "args": list(args),
        "bazel": {
            "executable": bazel,
            "version": got_bazel,
            "env": {k: env[k] for k in sorted(env) if k.startswith(("USE_BAZEL", "BAZELISK"))},
        },
        "overlay": overlay.record(),
        "rc": {"project_files": rc_files, "platform_file": str(rc)},
        "lockfile": {"path": str(lock), "sha256_before": lock_before, "mode": "error"},
    }
    with tempfile.TemporaryDirectory(prefix="dp-bazel-", dir=Path(cache) / "bazel") as td:
        bep = Path(td) / "bep.json" if command == "lint" else None
        full = argv(bazel, command, args, overlay.path, rc, bep=bep, places=places)
        record["argv"] = full
        code = run(full, cwd=project, env=env, capture=False).returncode
        record["exit"] = code
        option_args = [a for a in split_args(args)[0] if a.startswith("-")]

        def query(sub: list[str]) -> subprocess.CompletedProcess:
            verb, rest = sub[0], sub[1:]
            return run(
                [
                    bazel,
                    *startup_flags(rc, places),
                    verb,
                    *rest,
                    *enforced_flags(verb, overlay.path, places=places),
                ],
                cwd=project,
                env=env,
            )

        if command == "lint":
            outcome = lint_outcome(bep.read_text().splitlines() if bep and bep.is_file() else [])

            def has_sources(label: str) -> bool:
                q = query(
                    [
                        "query",
                        f'kind("source file", labels(srcs, {label}) + labels(srcs, labels(crate, {label})))',
                    ]
                )
                return q.returncode != 0 or bool(q.stdout.strip())

            problems += lint_problems(outcome, has_sources)
            record["lint"] = {"summary": lint_summary(outcome), "targets": outcome["targets"]}
        if audit:
            if command in ("build", "test", "coverage", "run", "lint"):
                aud = audit_rustc(
                    query,
                    patterns(args) or ["//..."],
                    option_args,
                    manifest["profiles"][profile]["tools"]["rust-toolchain"]["version"],
                )
                record["audit"] = aud
                problems += aud["problems"]
            else:
                problems.append(f"--audit applies to build, test, coverage, run and lint, not {command}")
    lock_after = _sha256(lock)
    record["lockfile"]["sha256_after"] = lock_after
    if lock_after != lock_before:
        problems.append(f"{LOCKFILE} changed during the run")
    record["problems"] = problems
    record["verified"] = code == 0 and not problems
    return (code if code != 0 else (EXIT_UNSATISFIED if problems else EXIT_OK)), record
