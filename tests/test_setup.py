"""`dev-platform setup`: locations, project pins, the pinned trusted tools, and the install/reuse/refusal paths.

The trusted installer here is a stand-in committed to a local platform repository (its digest is pinned like the
real one); the real installer's verification is covered by tests/test_install_release.py and, end to end against a
published release, by the homebrew workflow. The release, its verified snapshot and its `doctor` are real.
"""

import hashlib
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from dev_platform import locations as L
from dev_platform import projectsetup as S
from dev_platform import release
from dev_platform.digest import tree_digest
from dev_platform.errors import ConfigError
from dev_platform.resolve import default_store
from tests.helpers import ROOT, tmpdir
from tests.test_cli_e2e import TOOLCHAINS
from tests.test_pack import rmtree_rw

GIT_ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@i",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@i",
}

FAKE_INSTALLER = """\
import argparse, json, os, shutil, sys
from pathlib import Path
SOURCES = json.loads(%r)
ap = argparse.ArgumentParser()
for a in ("--version", "--store", "--verifier-sha256", "--policy", "--policy-sha256", "--archive-sha256",
          "--tree-sha256", "--source-revision"):
    ap.add_argument(a)
ap.add_argument("--allow-unaccepted", action="store_true")
ap.add_argument("--allow-prerelease", action="store_true")
a = ap.parse_args()
src = SOURCES[a.version]
if a.archive_sha256 != src["archive_sha256"] or a.tree_sha256 != src["tree"]:
    sys.exit(print("refused: verification failed: archive-digest", file=sys.stderr) or 1)
if not a.allow_unaccepted:
    sys.exit(print("refused: acceptance state 'verified-unaccepted' is not admitted", file=sys.stderr) or 1)
dest = Path(a.store) / a.version
if not dest.exists():
    shutil.copytree(src["dir"], dest)
    (Path(a.store) / ".records").mkdir(exist_ok=True)
    (Path(a.store) / ".records" / (a.version + ".verification.json")).write_text(json.dumps({
        "subject": {"version": a.version, "tree_digest": src["tree"], "archive_sha256": src["archive_sha256"]},
        "acceptance": {"state": "verified-unaccepted"},
        "installation": {"admitted_state": "verified-unaccepted", "tree_digest": src["tree"]}}))
print("installed %%s\\nacceptance: verified-unaccepted\\npin sha256 = %%s" %% (dest, src["tree"]))
"""


def git(d, *args):
    return subprocess.run(
        ["git", "-C", str(d), *args],
        capture_output=True,
        text=True,
        check=True,
        env={**os.environ, **GIT_ENV},
    ).stdout.strip()


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def build_release(test, version: str) -> tuple[Path, str]:
    out = tmpdir(test)
    test.addCleanup(rmtree_rw, out)
    tc = out / "toolchains.json"
    tc.write_text(json.dumps(TOOLCHAINS))
    vdir = release.build(ROOT / "src", tc, out / "built", version, strict_version=False)
    return vdir, tree_digest(vdir)


def platform_repo(test, sources: dict) -> tuple[Path, str, dict]:
    """A local stand-in of the public platform repository at one revision; returns (repo, revision, tool pins)."""
    d = tmpdir(test)
    files = {
        "tools/verify_release.py": "# verifier\n",
        "trust/policy.json": "{}\n",
        "tools/install_release.py": FAKE_INSTALLER % json.dumps(sources),
    }
    for rel, text in files.items():
        (d / rel).parent.mkdir(parents=True, exist_ok=True)
        (d / rel).write_text(text)
    git(d, "init", "-q")
    git(d, "add", "-A")
    git(d, "commit", "-qm", "platform")
    pins = {
        "verify_release.py_sha256": sha(files["tools/verify_release.py"]),
        "trust_policy_sha256": sha(files["trust/policy.json"]),
        "install_release.py_sha256": sha(files["tools/install_release.py"]),
    }
    return d, git(d, "rev-parse", "HEAD"), pins


def write_project(d: Path, version: str, tree: str, pins: dict) -> Path:
    d.mkdir(parents=True, exist_ok=True)
    (d / "dev-platform.toml").write_text(
        f'schema_version = 1\n[platform]\nversion = "{version}"\nsha256 = "{tree}"\nprofile = "py"\n'
        '[project]\nname = "consumer"\n[[check]]\nid = "t"\nadapter = "exec"\nargv = ["true"]\n'
        'stages = ["pre-merge", "full"]\nobligation = "always"\n'
    )
    (d / S.PINS_FILE).write_text(json.dumps(pins, indent=2))
    return d


class Locations(unittest.TestCase):
    def test_user_defaults_follow_xdg(self):
        loc = L.locate({})
        self.assertEqual(loc.scope, "user")
        self.assertEqual(loc.store, Path.home() / ".local/share/dev-platform/versions")
        self.assertEqual(loc.toolchains, Path.home() / ".local/share/dev-platform/toolchains")
        self.assertEqual(loc.cache, Path.home() / ".cache/dev-platform")
        loc = L.locate({"XDG_DATA_HOME": "/x/data", "XDG_CACHE_HOME": "/x/cache"})
        self.assertEqual(
            (loc.store, loc.cache), (Path("/x/data/dev-platform/versions"), Path("/x/cache/dev-platform"))
        )

    def test_home_variable_holds_everything_and_specific_overrides_win(self):
        loc = L.locate({"DEV_PLATFORM_HOME": "/h", "XDG_CACHE_HOME": "/x/cache"})
        self.assertEqual(
            (loc.store, loc.toolchains, loc.cache),
            (Path("/h/versions"), Path("/h/toolchains"), Path("/h/cache")),
        )
        loc = L.locate({"DEV_PLATFORM_HOME": "/h", "DEV_PLATFORM_STORE": "/s"}, toolchains=Path("/t"))
        self.assertEqual((loc.store, loc.toolchains), (Path("/s"), Path("/t")))
        self.assertEqual(
            loc.chosen_by,
            {"store": "DEV_PLATFORM_STORE", "toolchains": "--toolchains", "cache": "DEV_PLATFORM_HOME"},
        )
        loc = L.locate({"DEV_PLATFORM_STORE": "/s"}, store=Path("/flag"), home=Path("/fh"))
        self.assertEqual((loc.store, loc.cache, loc.scope), (Path("/flag"), Path("/fh/cache"), "explicit"))

    def test_ci_defaults_are_job_local_never_a_shared_home(self):
        env = {"CI": "true", "RUNNER_TEMP": "/job", "XDG_DATA_HOME": "/shared"}
        loc = L.locate(env)
        self.assertEqual(
            (loc.scope, loc.store, loc.cache),
            ("job", Path("/job/dev-platform/versions"), Path("/job/dev-platform/cache")),
        )
        with self.assertRaises(ConfigError):
            L.locate({"GITHUB_ACTIONS": "true"})
        self.assertEqual(L.locate({"GITHUB_ACTIONS": "true", "DEV_PLATFORM_HOME": "/h"}).scope, "explicit")

    def test_the_launcher_finds_the_store_under_the_home(self):
        self.assertEqual(default_store({"DEV_PLATFORM_HOME": "/h"}), Path("/h/versions"))
        self.assertEqual(default_store({"DEV_PLATFORM_HOME": "/h", "DEV_PLATFORM_STORE": "/s"}), Path("/s"))


PINS = {
    "version": "0.8.9",
    "source_revision": "c" * 40,
    "archive_sha256": "b" * 64,
    "tree_digest_pin": "a" * 64,
    "verifier_pins": {
        "verify_release.py_sha256": "1" * 64,
        "trust_policy_sha256": "2" * 64,
        "install_release.py_sha256": "3" * 64,
    },
}


class Project(unittest.TestCase):
    def test_found_from_a_subdirectory_but_not_when_explicit(self):
        d = write_project(tmpdir(self) / "p", "0.8.9", "a" * 64, PINS)
        (d / "src" / "deep").mkdir(parents=True)
        self.assertEqual(S.find_project(d / "src" / "deep", explicit=False), d.resolve())
        with self.assertRaises(S.Refused) as cm:
            S.find_project(d / "src", explicit=True)
        self.assertEqual(cm.exception.exit_code, 2)

    def test_the_two_pin_files_must_agree(self):
        d = write_project(tmpdir(self), "0.8.9", "a" * 64, PINS)
        cfg, pins = S.read_pins(d)
        self.assertEqual((cfg.platform.version, pins["version"]), ("0.8.9", "0.8.9"))
        for name, over in {
            "version": {"version": "0.8.8"},
            "tree_digest_pin": {"tree_digest_pin": "d" * 64},
            "source_revision": {"source_revision": "main"},
            "verifier_pins": {"verifier_pins": {}},
        }.items():
            write_project(d, "0.8.9", "a" * 64, {**PINS, **over})
            with self.assertRaises(S.Refused, msg=name) as cm:
                S.read_pins(d)
            self.assertIn(name, str(cm.exception))
            self.assertEqual(cm.exception.exit_code, 2)
        (d / S.PINS_FILE).unlink()
        with self.assertRaises(S.Refused) as cm:
            S.read_pins(d)
        self.assertIn("identity.json", str(cm.exception))

    def test_releases_before_pinned_provisioning_are_refused(self):
        d = write_project(tmpdir(self), "0.7.0", "a" * 64, {**PINS, "version": "0.7.0"})
        with self.assertRaises(S.Refused) as cm:
            S.read_pins(d)
        self.assertIn("predates", str(cm.exception))

    def test_the_platform_repository_itself_is_not_a_consumer(self):
        with self.assertRaises(S.Refused) as cm:
            S.read_pins(ROOT)
        self.assertIn("self-hosted", str(cm.exception))


class PinnedTools(unittest.TestCase):
    def test_tools_equal_to_their_pins_are_written_and_the_cache_is_reused(self):
        repo, rev, tool_pins = platform_repo(self, {})
        cache, pins = tmpdir(self), {**PINS, "source_revision": rev, "verifier_pins": tool_pins}
        out = S.pinned_tools(pins, cache, tmpdir(self), str(repo), S.run_process, dict(os.environ))
        self.assertEqual((out / "policy.json").read_text(), "{}\n")
        self.assertTrue((out / "tools" / "install_release.py").is_file())
        again = S.pinned_tools(pins, cache, tmpdir(self), "/nonexistent", S.run_process, dict(os.environ))
        self.assertEqual(
            (again / "tools" / "verify_release.py").read_text(), "# verifier\n"
        )  # no fetch needed

    def test_a_tool_that_differs_from_its_pin_is_an_integrity_refusal(self):
        repo, rev, tool_pins = platform_repo(self, {})
        pins = {
            **PINS,
            "source_revision": rev,
            "verifier_pins": {**tool_pins, "trust_policy_sha256": "9" * 64},
        }
        with self.assertRaises(S.Refused) as cm:
            S.pinned_tools(pins, tmpdir(self), tmpdir(self), str(repo), S.run_process, dict(os.environ))
        self.assertEqual(cm.exception.exit_code, 3)
        self.assertIn("trust/policy.json", str(cm.exception))

    def test_an_unknown_revision_is_refused(self):
        repo, _rev, tool_pins = platform_repo(self, {})
        pins = {**PINS, "source_revision": "f" * 40, "verifier_pins": tool_pins}
        with self.assertRaises(S.Refused) as cm:
            S.pinned_tools(pins, tmpdir(self), tmpdir(self), str(repo), S.run_process, dict(os.environ))
        self.assertIn("cannot fetch", str(cm.exception))


class FakeToolchains:
    """Stands in for the pinned release's `toolchain provision --pinned --verify` / `toolchain verify` (which
    download real toolchains); every other process (git, the installer, `doctor`) really runs."""

    def __init__(self, python=False):
        self.calls: list[tuple[list[str], dict]] = []
        self.python = python

    def __call__(self, argv, **kw):
        self.calls.append((list(argv), kw.get("env") or {}))
        if "toolchain" in argv:
            dest = Path(argv[argv.index("--dest") + 1]) if "--dest" in argv else None
            rec = {"conformant": True, "assurance": "certifiable", "identity_digest": "e" * 64}
            if "provision" in argv:
                (dest / "bin").mkdir(parents=True, exist_ok=True)
                (dest / "verified").write_text("ok")
                if self.python:  # a provisioned interpreter (here: one that runs this one)
                    exe = dest / "python" / "bin" / "python3"
                    exe.parent.mkdir(parents=True, exist_ok=True)
                    exe.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')
                    exe.chmod(0o755)
                return subprocess.CompletedProcess(argv, 0, json.dumps({"verification": rec}) + "\n", "")
            path0 = kw["env"]["PATH"].split(os.pathsep)[0]
            ok = (Path(path0).parent / "verified").is_file()
            return subprocess.CompletedProcess(argv, 0 if ok else 1, json.dumps(rec if ok else {}), "")
        return S.run_process(argv, **kw)

    def ran(self, word: str) -> int:
        """Processes that executed `word` (a command word or a script path; `git show rev:path` reads, not runs)."""
        return sum(
            any(a == word or (a.endswith("/" + word) and ":" not in a) for a in argv)
            for argv, _ in self.calls
        )


class Setup(unittest.TestCase):
    def setUp(self):
        self.vdir, self.tree = build_release(self, "0.8.9")
        self.vdir2, self.tree2 = build_release(self, "0.8.10")
        sources = {
            "0.8.9": {"dir": str(self.vdir), "archive_sha256": "b" * 64, "tree": self.tree},
            "0.8.10": {"dir": str(self.vdir2), "archive_sha256": "d" * 64, "tree": self.tree2},
        }
        self.repo, rev, tool_pins = platform_repo(self, sources)
        self.pins = {
            "version": "0.8.9",
            "source_revision": rev,
            "archive_sha256": "b" * 64,
            "tree_digest_pin": self.tree,
            "verifier_pins": tool_pins,
        }
        self.project = write_project(tmpdir(self) / "consumer", "0.8.9", self.tree, self.pins)
        home = tmpdir(self)
        self.addCleanup(rmtree_rw, home)
        self.loc = L.locate({}, home=home)
        bindir = tmpdir(self)
        (bindir / "gh").write_text("#!/bin/sh\nexit 0\n")
        (bindir / "gh").chmod(0o755)
        self.env = {**os.environ, "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}", "GH_TOKEN": "sentinel"}
        for k in ("CI", "GITHUB_ACTIONS", "PYTHONPATH", "DEV_PLATFORM_OVERRIDE"):
            self.env.pop(k, None)

    def setup(self, project=None, run=None, **kw):
        kw.setdefault("allow_unaccepted", True)
        run = run or FakeToolchains()
        rec, code = S.setup(
            project or self.project, self.loc, repo_url=str(self.repo), env=self.env, run=run, **kw
        )
        return rec, code, run

    def snapshot(self, d: Path) -> dict:
        return {p.name: p.read_bytes() for p in d.iterdir() if p.is_file()}

    def test_first_setup_installs_verifies_provisions_and_checks(self):
        before = self.snapshot(self.project)
        rec, code, run = self.setup()
        self.assertEqual(code, 0, rec.get("problem"))
        self.assertEqual(rec["release"]["action"], "installed")
        self.assertEqual(rec["release"]["state"], "verified-unaccepted")
        self.assertEqual(tree_digest(self.loc.store / "0.8.9"), self.tree)
        self.assertEqual(rec["toolchain"]["action"], "provisioned")
        self.assertEqual(rec["toolchain"]["path"], str(self.loc.toolchains / "0.8.9" / "py"))
        self.assertEqual(rec["doctor"]["exit"], 0, rec["doctor"])
        self.assertEqual(rec["env"]["DEV_PLATFORM_STORE"], str(self.loc.store))
        self.assertEqual(self.snapshot(self.project), before)  # pins are only read: never an upgrade
        token_holders = [argv for argv, env in run.calls if env.get("GH_TOKEN") == "sentinel"]
        self.assertEqual(len(token_holders), 1)
        self.assertTrue(token_holders[0][2].endswith("install_release.py"))

    def test_doctor_runs_the_pinned_release_not_the_cli(self):
        rec, code, run = self.setup()
        self.assertEqual(code, 0, rec.get("problem"))
        argv, env = next((a, e) for a, e in run.calls if "doctor" in a)
        self.assertIn("-P", argv)
        self.assertEqual(env["DEV_PLATFORM_REEXEC"], "0.8.9")
        self.assertNotEqual(Path(env["PYTHONPATH"]), ROOT / "src")  # a private verified snapshot

    def test_a_profile_verifying_the_running_python_runs_the_release_on_the_provisioned_one(self):
        rec, code, run = self.setup(run=FakeToolchains(python=True))
        self.assertEqual(code, 0, rec.get("problem"))
        exe = str(self.loc.toolchains / "0.8.9" / "py" / "python" / "bin" / "python3")
        self.assertEqual(rec["env"]["DEV_PLATFORM_PYTHON"], exe)
        self.assertIn(f"export DEV_PLATFORM_PYTHON={exe}", S.shell_env(rec))
        provision = next(a for a, _ in run.calls if "provision" in a)
        self.assertEqual(provision[0], sys.executable)  # producing bytes needs no particular interpreter
        for word in ("verify", "doctor"):  # identity is verified on, and the release then runs on, that one
            self.assertEqual(next(a for a, _ in run.calls if word in a)[0], exe, word)
        self.assertEqual(rec["doctor"]["exit"], 0, rec["doctor"])

    def test_second_setup_reuses_without_reinstalling_or_reprovisioning(self):
        self.setup()
        rec, code, run = self.setup()
        self.assertEqual(code, 0, rec.get("problem"))
        self.assertEqual((rec["release"]["action"], rec["toolchain"]["action"]), ("present", "reused"))
        self.assertEqual(run.ran("install_release.py"), 0)
        self.assertEqual(run.ran("provision"), 0)

    def test_a_verified_release_needs_no_flag_and_older_states_keep_theirs(self):
        S.admit("verified", allow_unaccepted=False, allow_prerelease=False)
        S.admit("accepted", allow_unaccepted=False, allow_prerelease=False)
        for state, flag in (
            ("verified-unaccepted", "--allow-unaccepted"),
            ("pre-release", "--allow-prerelease"),
        ):
            with self.assertRaisesRegex(S.Refused, flag):
                S.admit(state, allow_unaccepted=False, allow_prerelease=False)
        with self.assertRaisesRegex(S.Refused, "not admitted"):
            S.admit("failed", allow_unaccepted=True, allow_prerelease=True)

    def test_an_unaccepted_release_needs_the_consumers_explicit_admission(self):
        rec, code, _ = self.setup(allow_unaccepted=False)
        self.assertEqual(code, 1)
        self.assertIn("not admitted", rec["problem"])
        self.assertFalse((self.loc.store / "0.8.9").exists())
        self.setup()
        rec, code, run = self.setup(allow_unaccepted=False)  # installed earlier: admission is still per use
        self.assertEqual(code, 1)
        self.assertIn("--allow-unaccepted", rec["problem"])
        self.assertEqual(run.ran("doctor"), 0)

    def test_a_corrupted_store_entry_is_refused_and_left_untouched(self):
        self.setup()
        f = self.loc.store / "0.8.9" / "src" / "dev_platform" / "cli.py"
        f.parent.chmod(0o700)
        f.chmod(0o600)
        f.write_text(f.read_text() + "\n# tampered\n")
        rec, code, run = self.setup()
        self.assertEqual(code, 3)
        self.assertIn("not the pinned", rec["problem"])
        self.assertTrue(f.read_text().endswith("# tampered\n"))
        self.assertEqual(run.ran("install_release.py") + run.ran("doctor"), 0)

    def test_a_mismatched_release_identity_installs_nothing(self):
        bad = {**self.pins, "archive_sha256": "0" * 64}
        write_project(self.project, "0.8.9", self.tree, bad)
        rec, code, run = self.setup()
        self.assertEqual(code, 1)
        self.assertIn("trusted installer refused", rec["problem"])
        self.assertFalse((self.loc.store / "0.8.9").exists())
        write_project(
            self.project,
            "0.8.9",
            self.tree,
            {
                **self.pins,
                "verifier_pins": {**self.pins["verifier_pins"], "install_release.py_sha256": "0" * 64},
            },
        )
        rec, code, run = self.setup()
        self.assertEqual(code, 3)
        self.assertEqual(run.ran("install_release.py"), 0)

    def test_a_release_without_the_installers_record_needs_reverification(self):
        self.setup()
        (self.loc.store / ".records" / "0.8.9.verification.json").unlink()
        rec, code, _ = self.setup()
        self.assertEqual(code, 1)
        self.assertIn("--reverify", rec["problem"])
        rec, code, run = self.setup(reverify=True)
        self.assertEqual(code, 0, rec.get("problem"))
        self.assertEqual(rec["release"]["action"], "reverified")
        self.assertEqual(run.ran("install_release.py"), 1)

    def test_versions_coexist_and_each_project_gets_its_own(self):
        pins2 = {**self.pins, "version": "0.8.10", "archive_sha256": "d" * 64, "tree_digest_pin": self.tree2}
        other = write_project(tmpdir(self) / "other", "0.8.10", self.tree2, pins2)
        for proj, ver in ((self.project, "0.8.9"), (other, "0.8.10"), (self.project, "0.8.9")):
            rec, code, run = self.setup(project=proj)
            self.assertEqual(code, 0, rec.get("problem"))
            self.assertEqual(rec["pinned"]["version"], ver)
            self.assertEqual(rec["toolchain"]["path"], str(self.loc.toolchains / ver / "py"))
            _argv, env = next((a, e) for a, e in run.calls if "doctor" in a)
            self.assertEqual(env["DEV_PLATFORM_REEXEC"], ver)
        self.assertEqual(
            sorted(p.name for p in self.loc.store.iterdir() if not p.name.startswith(".")),
            ["0.8.10", "0.8.9"],
        )
        self.assertEqual(tree_digest(self.loc.store / "0.8.9"), self.tree)

    def test_dry_run_writes_nothing(self):
        rec, code, run = self.setup(dry_run=True)
        self.assertEqual(code, 0)
        self.assertEqual(
            (rec["release"]["action"], rec["toolchain"]["action"]), ("would install", "would provision")
        )
        self.assertEqual(run.calls, [])
        self.assertFalse(self.loc.store.exists() or self.loc.cache.exists())

    def test_an_override_is_never_set_up(self):
        self.env["DEV_PLATFORM_OVERRIDE"] = str(ROOT)
        rec, code, _ = self.setup()
        self.assertEqual(code, 2)
        self.assertIn("DEV_PLATFORM_OVERRIDE", rec["problem"])

    def test_gh_is_required_only_to_install(self):
        self.env["PATH"] = "/nonexistent"
        rec, code, _ = self.setup()
        self.assertEqual(code, 1)
        self.assertIn("gh auth login", rec["problem"])

    def test_shell_exports(self):
        rec, code, _ = self.setup()
        self.assertEqual(code, 0, rec.get("problem"))
        out = S.shell_env(rec)
        self.assertIn(f"export DEV_PLATFORM_STORE={self.loc.store}", out)
        self.assertIn(str(self.loc.toolchains / "0.8.9" / "py" / "bin"), out)
        self.assertTrue(out.splitlines()[-1].endswith(':"$PATH"'))
        self.assertIn("unset DEV_PLATFORM_PYTHON", out)
        r = subprocess.run(
            ["sh", "-c", out + '\nprintf %s "$DEV_PLATFORM_STORE"'], capture_output=True, text=True
        )
        self.assertEqual(r.stdout, str(self.loc.store))
        self.assertIn("ready", S.render(rec))


class UnsupportedHost(unittest.TestCase):
    """A host the release has no toolchain sources for (Linux arm64, an Intel Mac) is refused by name, before
    provisioning, instead of provisioning nothing and failing verification without saying why."""

    MANIFEST = {
        "profiles": {
            "rust-bazel-9": {
                "tools": {
                    "bazelisk": {"version": "1.29.0", "source": {"darwin-arm64": {}, "linux-x86_64": {}}},
                    "bazel": {"version": "9.2.0", "bazel_managed": True},
                }
            }
        }
    }

    def test_refused_with_the_host_and_the_supported_platforms(self):
        res = SimpleNamespace(
            release={"toolchains": self.MANIFEST}, version="0.10.0", cleanup=str(tmpdir(self))
        )
        loc = L.locate({}, home=tmpdir(self))
        with (
            mock.patch.object(S, "platform_key", return_value="linux-aarch64"),
            self.assertRaises(S.Refused) as e,
        ):
            S.ensure_toolchain(res, "rust-bazel-9", tmpdir(self), loc, {}, run=S.run_process)
        msg = str(e.exception)
        self.assertIn(
            "no pinned source of bazelisk (profile 'rust-bazel-9') for this host (linux-aarch64)", msg
        )
        self.assertIn("it supports darwin-arm64, linux-x86_64", msg)
        self.assertEqual(e.exception.exit_code, 1)
        self.assertFalse(loc.toolchains.exists())

    def test_only_hosts_with_every_tool_are_named(self):
        manifest = {
            "profiles": {"p": {"tools": {"a": {"source": {"darwin-arm64": {}}}, "b": {"source": {"x": {}}}}}}
        }
        res = SimpleNamespace(release={"toolchains": manifest}, version="0.10.0", cleanup=str(tmpdir(self)))
        with (
            mock.patch.object(S, "platform_key", return_value="darwin-arm64"),
            self.assertRaises(S.Refused) as e,
        ):
            S.ensure_toolchain(res, "p", tmpdir(self), L.locate({}, home=tmpdir(self)), {}, run=S.run_process)
        self.assertIn("no host has a source for every tool", str(e.exception))

    def test_supported_hosts_and_unsourced_tools_pass(self):
        for key in ("darwin-arm64", "linux-x86_64"):
            self.assertEqual(S.unsupported_tools(self.MANIFEST, "rust-bazel-9", key), [])
        self.assertEqual(S.unsupported_tools(self.MANIFEST, "rust-bazel-9", "darwin-x86_64"), ["bazelisk"])


class MaterializeInSetup(unittest.TestCase):
    """Setup writes the release's Bazel configuration before verifying, and refuses what it must not touch."""

    MANIFEST = {"profiles": {"p": {"bazel": {}, "tools": {"a": {"version": "1"}}}}}

    def run_setup(self, run):
        res = SimpleNamespace(
            release={"toolchains": self.MANIFEST}, version="0.13.0", cleanup=str(tmpdir(self))
        )
        loc = L.locate({}, home=tmpdir(self))
        return S.ensure_toolchain(res, "p", tmpdir(self), loc, {}, run=run)

    def test_materialize_runs_first_and_never_adds_hooks_to_existing_files(self):
        calls = []

        def run(argv, **kw):
            calls.append(list(argv))
            rec = {"conformant": True, "assurance": "certifiable", "identity_digest": "e" * 64}
            out = {
                "written": ["dev-platform/bazel.bazelrc"],
                "unchanged": [],
                "added_hooks": [],
                "refused": [],
            }
            return subprocess.CompletedProcess(argv, 0, json.dumps(out if "materialize" in argv else rec), "")

        with mock.patch.object(S, "unsupported_tools", return_value=[]):
            out = self.run_setup(run)
        self.assertIn("materialize", calls[0])
        self.assertIn("--create-hooks", calls[0])
        self.assertNotIn("--add-hooks", calls[0])
        self.assertEqual(out["bazel_config"]["written"], ["dev-platform/bazel.bazelrc"])

    def test_a_mismatching_bazelversion_stops_setup_before_provisioning(self):
        conflicts = [
            {
                "path": ".bazelversion",
                "detail": "selects Bazel 9.2.0; the profile pins Bazel 9.3.1",
                "action": "set .bazelversion to 9.3.1",
            }
        ]
        calls = []

        def run(argv, **kw):
            calls.append(list(argv))
            return subprocess.CompletedProcess(
                argv, 1, json.dumps({"refused": [], "conflicts": conflicts}), ""
            )

        with mock.patch.object(S, "unsupported_tools", return_value=[]), self.assertRaises(S.Refused) as e:
            self.run_setup(run)
        self.assertIn(".bazelversion: selects Bazel 9.2.0; the profile pins Bazel 9.3.1", str(e.exception))
        self.assertIn("set .bazelversion to 9.3.1", str(e.exception))
        self.assertEqual(len(calls), 1)  # nothing was provisioned or verified

    def test_a_foreign_file_is_refused_with_the_correction(self):
        refused = [{"path": "ruff.toml", "detail": "not generated by dev-platform", "action": "remove it"}]

        def run(argv, **kw):
            return subprocess.CompletedProcess(argv, 1, json.dumps({"refused": refused}), "")

        with mock.patch.object(S, "unsupported_tools", return_value=[]), self.assertRaises(S.Refused) as e:
            self.run_setup(run)
        self.assertIn("ruff.toml: not generated by dev-platform -> remove it", str(e.exception))


class Cli(unittest.TestCase):
    def test_setup_reports_a_missing_project_with_usage_status(self):
        d = tmpdir(self)
        env = {k: v for k, v in os.environ.items() if k not in ("CI", "GITHUB_ACTIONS")}
        r = subprocess.run(
            [
                sys.executable,
                "-m",
                "dev_platform",
                "setup",
                "--project",
                str(d),
                "--home",
                str(d),
                "--dry-run",
            ],
            capture_output=True,
            text=True,
            env={**env, "PYTHONPATH": str(ROOT / "src")},
        )
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("no dev-platform.toml", r.stdout)
