"""Consumer compatibility (M3): synthetic Python, Rust and mixed consumers against real,
installed, side-by-side platform releases.

Releases are built, packed and installed through the same code paths operators use. Host tools are
emulated where real ones would make the suite non-hermetic (fake `bazel`/`cargo` on PATH; a
python-emulated `rustc` probe). Production consumers are not involved.
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

from dev_platform import closure, pack, release
from dev_platform.digest import tree_digest
from tests.helpers import ROOT, copy_fixture, tmpdir
from tests.test_pack import rmtree_rw

RUSTC = "178492c5c6cef1d38a86c79f48fb8e4164ba0dbaaa9dcd0aa0bb4ff383c22ab9"
CPYTHON = "c90d47a795a62032128d98c74b4c3d64cbabf93684dc582ee27255be64193711"
BAZELISK = "70a8ed978aefe7116ab7ba18380a0acd6e7d84b1eca0c151b90f85f5c1adfec3"
PYCLOSURE = {
    "kind": "file",
    "sha256": {closure.platform_key(): closure.digest(Path(sys.executable).resolve())[0]},
    # Test-only: the host interpreter links host libraries; the real manifests list real system libs.
    "system_libs": ["/", "lib"],
}
PYVER = "{}.{}.".format(*sys.version_info[:2])


def bazel_tool(bazel_version, rust_sha=RUSTC, extra=None):
    tools = {
        "bazel": {
            "version": bazel_version,
            "bazel_managed": True,
            "declared_in": {"file": ".bazelversion", "pattern": r"(\S+)"},
            "integrity": [
                {
                    "name": "bazelisk-pinned-binary",
                    "file": ".bazeliskrc",
                    "pattern": r"BAZELISK_VERIFY_SHA256=([0-9a-f]{64})",
                    "sha256": BAZELISK,
                }
            ],
        },
        "rust-toolchain": {
            "version": "1.85.0",
            "bazel_managed": True,
            "declared_in": {"file": "MODULE.bazel", "pattern": r'versions = \["([^"]+)"\]'},
            "integrity": [
                {
                    "name": "rustc-archive",
                    "file": "MODULE.bazel",
                    "pattern": r'rust\.toolchain\([^)]*sha256 = "([0-9a-f]{64})"',
                    "sha256": rust_sha,
                    "lock_file": "MODULE.bazel.lock",
                }
            ],
        },
    }
    tools.update(extra or {})
    return {"tools": tools}


def manifest(bazel_version="8.1.0"):
    py_probe = {"argv": ["{python}", "--version"], "pattern": r"Python (\S+)"}
    mixed_py = {
        "python-toolchain": {
            "version": "3.12.3",
            "bazel_managed": True,
            "declared_in": {"file": "MODULE.bazel", "pattern": r'python_version = "([^"]+)"'},
            "integrity": [
                {
                    "name": "cpython-archive",
                    "file": "MODULE.bazel",
                    "pattern": r'python\.toolchain\([^)]*sha256 = "([0-9a-f]{64})"',
                    "sha256": CPYTHON,
                    "lock_file": "MODULE.bazel.lock",
                }
            ],
        }
    }
    return {
        "schema": "dev-platform.toolchains/v1",
        "profiles": {
            "python": {
                "tools": {
                    "python": {"version": PYVER, "compare": "prefix", "closure": PYCLOSURE, "probe": py_probe}
                }
            },
            "python-weak": {"tools": {"python": {"version": PYVER, "compare": "prefix", "probe": py_probe}}},
            "rust-bazel": bazel_tool(bazel_version),
            "mixed-bazel": bazel_tool(bazel_version, extra=mixed_py),
            "rust-cargo": {
                "tools": {
                    "rustc": {
                        "version": "1.85.0",
                        "probe": {
                            "argv": ["{python}", "-c", "print('rustc 1.85.0')"],
                            "pattern": r"rustc (\S+)",
                        },
                    }
                }
            },
        },
    }


class Platform:
    """Builds, packs and installs releases into one store, like an operator would."""

    def __init__(self, test):
        self.test = test
        self.work = tmpdir(test)
        test.addCleanup(rmtree_rw, self.work)
        self.store = self.work / "store"
        self.digests = {}

    def publish(self, version, bazel_version="8.1.0"):
        src = self.work / f"src-{version}"
        shutil.copytree(ROOT / "src", src, ignore=shutil.ignore_patterns("__pycache__"))
        init = src / "dev_platform" / "__init__.py"
        init.write_text(re.sub(r'__version__ = "[^"]+"', f'__version__ = "{version}"', init.read_text()))
        tc = self.work / f"tc-{version}.json"
        tc.write_text(json.dumps(manifest(bazel_version)))
        d = release.build(src, tc, self.work / "build", version, source_revision="a" * 40)
        arc = self.work / f"{version}.tar.gz"
        sha = pack.pack(d, arc)
        pack.install(arc, self.store, expect_archive_sha256=sha, expect_tree_sha256=tree_digest(d))
        self.digests[version] = tree_digest(d)
        return self.digests[version]


def fake_bin(test, bazel_exit=0):
    d = tmpdir(test) / "bin"
    d.mkdir()
    for tool, code in (("bazel", bazel_exit), ("cargo", 0)):
        p = d / tool
        p.write_text(f'#!/bin/sh\necho fake {tool} "$@" >&2\nexit {code}\n')
        p.chmod(0o755)
    return d


def run(project, store, *args, path=None, env_extra=None):
    env = {k: v for k, v in os.environ.items() if k not in ("CI", "GITHUB_ACTIONS", "PYTHONPATH")}
    env.update({"PYTHONPATH": str(ROOT / "src"), "DEV_PLATFORM_STORE": str(store), **(env_extra or {})})
    if path:
        env["PATH"] = f"{path}{os.pathsep}{env['PATH']}"
    argv = [args[0], "--project", str(project), *args[1:]]
    return subprocess.run(
        [sys.executable, "-m", "dev_platform", *argv], capture_output=True, text=True, env=env
    )


def init(project, store, version, profile, force=False):
    extra = ["--force"] if force else []
    r = run(project, store, "init", "--platform-version", version, "--profile", profile, *extra)
    assert r.returncode == 0, r.stderr


def commit_all(project):
    for cmd in (
        ["init", "-q"],
        ["add", "-A"],
        ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "c"],
    ):
        subprocess.run(["git", *cmd], cwd=project, check=True, capture_output=True)


class CompatBase(unittest.TestCase):
    def setUp(self):
        self.p = Platform(self)
        self.a = self.p.publish("1.0.0")
        self.b = self.p.publish("1.0.1", bazel_version="8.2.0")  # a toolchain upgrade = a new release


class PythonConsumerTest(CompatBase):
    def test_pinned_install_validation_and_certification(self):
        proj = copy_fixture(self, "python-only")
        init(proj, self.p.store, "1.0.0", "python")
        commit_all(proj)
        r = run(proj, self.p.store, "check", "--stage", "full", "--json")
        doc = json.loads(r.stdout)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(doc["platform"]["running_version"], "1.0.0")
        env = doc["environment"]
        self.assertEqual((env["assurance"], env["tools"][0]["identity"]), ("certifiable", "closure-verified"))
        self.assertTrue(doc["certification"]["certified"], doc["certification"])

    def test_weak_profile_validates_but_cannot_certify(self):
        proj = copy_fixture(self, "python-only")
        init(proj, self.p.store, "1.0.0", "python-weak")
        commit_all(proj)
        doc = json.loads(run(proj, self.p.store, "check", "--stage", "full", "--json").stdout)
        self.assertEqual(doc["admission"], "admitted")
        self.assertEqual(doc["environment"]["assurance"], "diagnostic")
        self.assertFalse(doc["certification"]["certified"])

    def test_side_by_side_upgrade_and_rollback(self):
        proj = copy_fixture(self, "python-only")
        init(proj, self.p.store, "1.0.0", "python")
        self.assertEqual(
            json.loads(run(proj, self.p.store, "check", "--changed", "app.py", "--json").stdout)["platform"][
                "running_version"
            ],
            "1.0.0",
        )
        init(proj, self.p.store, "1.0.1", "python", force=True)  # upgrade = explicit edit of the pin
        doc = json.loads(run(proj, self.p.store, "check", "--changed", "app.py", "--json").stdout)
        self.assertEqual(
            (doc["platform"]["running_version"], doc["environment"]["release"]["tree_digest"]),
            ("1.0.1", self.b),
        )
        init(proj, self.p.store, "1.0.0", "python", force=True)  # rollback = select the earlier release
        doc = json.loads(run(proj, self.p.store, "check", "--changed", "app.py", "--json").stdout)
        self.assertEqual(
            (doc["platform"]["running_version"], doc["environment"]["release"]["tree_digest"]),
            ("1.0.0", self.a),
        )
        self.assertEqual(tree_digest(self.p.store / "1.0.0"), self.a)  # untouched by the upgrade

    def test_failed_verification_paths(self):
        proj = copy_fixture(self, "python-only")
        init(proj, self.p.store, "1.0.0", "python")
        # tampering with the installed release (made writable first, as an attacker would)
        target = self.p.store / "1.0.0" / "src" / "dev_platform" / "model.py"
        os.chmod(target.parent, 0o755)
        os.chmod(target, 0o644)
        target.write_text(target.read_text() + "\n# tampered\n")
        r = run(proj, self.p.store, "check", "--changed", "app.py")
        self.assertEqual(r.returncode, 3)
        self.assertIn("integrity failure", r.stderr)
        # a consumer pinned to the other release is unaffected
        init(proj, self.p.store, "1.0.1", "python", force=True)
        self.assertEqual(run(proj, self.p.store, "check", "--changed", "app.py").returncode, 0)

    def test_version_mismatch_paths(self):
        proj = copy_fixture(self, "python-only")
        init(proj, self.p.store, "1.0.0", "python")
        cfg = proj / "dev-platform.toml"
        text = cfg.read_text()
        cfg.write_text(text.replace('version = "1.0.0"', 'version = "1.0.2"'))
        r = run(proj, self.p.store, "check", "--changed", "app.py")
        self.assertEqual((r.returncode, "not installed" in r.stderr), (3, True))
        # right version, digest of a different release
        cfg.write_text(text.replace(self.a, self.b))
        r = run(proj, self.p.store, "check", "--changed", "app.py")
        self.assertEqual((r.returncode, "integrity failure" in r.stderr), (3, True))
        # unknown profile
        cfg.write_text(text.replace('profile = "python"', 'profile = "nope"'))
        self.assertEqual(run(proj, self.p.store, "check", "--changed", "app.py").returncode, 2)

    def test_installer_refuses_bad_archives_and_leaves_store_untouched(self):
        before = sorted(p.name for p in self.p.store.iterdir())
        arc = self.p.work / "1.0.0.tar.gz"
        r = run(
            self.p.work,
            self.p.store,
            "release",
            "install",
            str(arc),
            "--archive-sha256",
            "0" * 64,
            "--store",
            str(self.p.store),
        )
        self.assertEqual(r.returncode, 2)
        evil = self.p.work / "evil.tar.gz"
        evil.write_bytes(arc.read_bytes()[:-8] + b"garbage!")
        sha = hashlib.sha256(evil.read_bytes()).hexdigest()
        r = run(
            self.p.work,
            self.p.store,
            "release",
            "install",
            str(evil),
            "--archive-sha256",
            sha,
            "--store",
            str(self.p.store),
        )
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(sorted(p.name for p in self.p.store.iterdir()), before)


class BazelConsumersTest(CompatBase):
    def consumer(self, fixture, profile, version="1.0.0"):
        proj = copy_fixture(self, fixture)
        init(proj, self.p.store, version, profile)
        return proj

    def test_bazel_only_rust_consumer_end_to_end(self):
        proj = self.consumer("rust-bazel", "rust-bazel")
        cfg = (proj / "dev-platform.toml").read_text()
        self.assertIn("bazel_only = true", cfg)
        self.assertNotIn("cargo", cfg)
        fake = fake_bin(self, 0)
        doc = json.loads(
            run(proj, self.p.store, "check", "--changed", "src/lib.rs", "--json", path=fake).stdout
        )
        self.assertEqual(doc["admission"], "admitted")
        self.assertEqual(doc["checks"][0]["command"][:2], ["bazel", "test"])
        env = doc["environment"]
        self.assertEqual((env["conformant"], env["assurance"]), (True, "certifiable"))
        self.assertEqual({t["identity"] for t in env["tools"]}, {"bazel-locked"})

    def test_failing_bazel_blocks_admission(self):
        proj = self.consumer("rust-bazel", "rust-bazel")
        r = run(proj, self.p.store, "check", "--changed", "src/lib.rs", path=fake_bin(self, 1))
        self.assertEqual(r.returncode, 1)
        self.assertIn("admission: blocked", r.stdout)

    def test_mixed_language_bazel_consumer(self):
        proj = self.consumer("mixed-bazel", "mixed-bazel")
        doc = json.loads(
            run(
                proj, self.p.store, "check", "--changed", "py/app.py", "--json", path=fake_bin(self, 0)
            ).stdout
        )
        self.assertEqual(doc["admission"], "admitted")
        names = {t["name"] for t in doc["environment"]["tools"]}
        self.assertEqual(names, {"bazel", "rust-toolchain", "python-toolchain"})
        self.assertEqual(doc["environment"]["assurance"], "certifiable")

    def test_cargo_consumer_and_bazel_only_prohibition(self):
        proj = copy_fixture(self, "rust-cargo")
        init(proj, self.p.store, "1.0.0", "rust-cargo")
        self.assertIn('adapter = "cargo"', (proj / "dev-platform.toml").read_text())
        doc = json.loads(
            run(proj, self.p.store, "check", "--changed", "src/lib.rs", "--json", path=fake_bin(self)).stdout
        )
        self.assertEqual(doc["checks"][0]["command"][0], "cargo")
        # the same project declaring bazel_only must reject the cargo adapter outright
        cfg = proj / "dev-platform.toml"
        cfg.write_text(cfg.read_text().replace("bazel_only = false", "bazel_only = true"))
        r = run(proj, self.p.store, "check", "--changed", "src/lib.rs", path=fake_bin(self))
        self.assertEqual(r.returncode, 2)
        self.assertIn("cargo adapter is prohibited", r.stderr)

    def test_declaration_drift_is_detected_not_papered_over(self):
        for name, edit in {
            "bazel version": (".bazelversion", "8.0.0\n", None),
            "toolchain digest changed": ("MODULE.bazel", None, (RUSTC, "f" * 64)),
            "digest missing from resolved graph": ("MODULE.bazel.lock", None, (RUSTC, "e" * 64)),
            "bazelisk pin removed": (".bazeliskrc", "", None),
        }.items():
            proj = self.consumer("rust-bazel", "rust-bazel")
            f, new, swap = edit
            path = proj / f
            path.write_text(new if swap is None else path.read_text().replace(*swap))
            doc = json.loads(
                run(
                    proj, self.p.store, "check", "--changed", "src/lib.rs", "--json", path=fake_bin(self)
                ).stdout
            )
            self.assertFalse(doc["environment"]["conformant"], name)
            self.assertEqual(doc["admission"], "blocked", name)
            self.assertEqual(doc["environment"]["assurance"], "diagnostic", name)

    def test_toolchain_upgrade_is_an_explicit_two_step_and_rolls_back(self):
        proj = self.consumer("rust-bazel", "rust-bazel", "1.0.0")
        fake = fake_bin(self)

        def go():
            return json.loads(
                run(proj, self.p.store, "check", "--changed", "src/lib.rs", "--json", path=fake).stdout
            )

        self.assertTrue(go()["environment"]["conformant"])
        init(proj, self.p.store, "1.0.1", "rust-bazel", force=True)  # new release expects Bazel 8.2.0
        self.assertFalse(go()["environment"]["conformant"])  # consumer has not upgraded its declaration
        (proj / ".bazelversion").write_text("8.2.0\n")
        doc = go()
        self.assertTrue(doc["environment"]["conformant"])
        self.assertEqual(doc["environment"]["release"]["tree_digest"], self.b)
        # rollback: previous release and the previous declaration, both explicit
        init(proj, self.p.store, "1.0.0", "rust-bazel", force=True)
        (proj / ".bazelversion").write_text("8.1.0\n")
        doc = go()
        self.assertTrue(doc["environment"]["conformant"])
        self.assertEqual(doc["environment"]["release"]["tree_digest"], self.a)

    def test_environment_identity_changes_with_the_release_profile(self):
        proj = self.consumer("rust-bazel", "rust-bazel", "1.0.0")
        d1 = json.loads(run(proj, self.p.store, "explain", "--changed", "src/lib.rs", "--json").stdout)
        (proj / ".bazelversion").write_text("8.2.0\n")
        init(proj, self.p.store, "1.0.1", "rust-bazel", force=True)
        d2 = json.loads(run(proj, self.p.store, "explain", "--changed", "src/lib.rs", "--json").stdout)
        self.assertNotEqual(d1["environment"]["identity_digest"], d2["environment"]["identity_digest"])


if __name__ == "__main__":
    unittest.main()
