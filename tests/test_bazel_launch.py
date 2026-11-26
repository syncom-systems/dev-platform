"""`dev-platform bazel` (ADR 0028, Design C): argument policy, the rules_rust overlay, lint evidence, the audit
and the run, without network or Bazel (a fake rules_rust archive with the real anchors, a fake runner)."""

from __future__ import annotations

import base64
import copy
import hashlib
import io
import json
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path

from dev_platform import bazel_launch as bl
from dev_platform import toolchain
from dev_platform.errors import ConfigError

ROOT = Path(__file__).resolve().parents[1]
PROFILE = "rust-aarch64-none-bazel-9.3"
MANIFEST = toolchain.validate(json.loads((ROOT / "toolchains" / "manifest.json").read_text()))

FAKE_MODULE = 'module(name = "rules_rust", version = "0.74.0")\n\nrust.toolchain(edition = "2021")\n'
FAKE_EXT = (
    "def _rust_impl(module_ctx):\n"
    "    toolchains = root.tags.toolchain or rules_rust.tags.toolchain\n"
    "    for toolchain in toolchains:\n"
    "        x(\n"
    "                edition = toolchain.edition,\n"
    "        )\n"
)


def _tarball(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, text in sorted(files.items()):
            data = text.encode()
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


class FakeSources:
    """BCR source.json and the archive it names, served by a fetch that verifies like provision.fetch."""

    def __init__(self, files: dict[str, str] | None = None, extra: dict | None = None):
        self.archive = _tarball(files or {"MODULE.bazel": FAKE_MODULE, "rust/extensions.bzl": FAKE_EXT})
        sri = "sha256-" + base64.b64encode(hashlib.sha256(self.archive).digest()).decode()
        self.source = json.dumps(
            {"integrity": sri, "strip_prefix": "", "url": "https://x/rr.tar.gz", **(extra or {})}
        )
        self.fetched: list[str] = []

    def manifest(self) -> dict:
        m = copy.deepcopy(MANIFEST)
        pin = bl.rules_rust_pin(m, PROFILE)
        pin["source_json_sha256"] = hashlib.sha256(self.source.encode()).hexdigest()
        return m

    def fetch(self, url: str, sha256: str, dest: Path) -> None:
        self.fetched.append(url)
        data = self.source.encode() if url.endswith("source.json") else self.archive
        if hashlib.sha256(data).hexdigest() != sha256:
            raise ConfigError([f"hash mismatch for {url}"])
        dest.write_bytes(data)


def _cp(code: int = 0, out: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess([], code, out, "")


class ArgumentPolicy(unittest.TestCase):
    def test_denied_options_in_every_form(self):
        for arg in (
            "--override_repository=rules_rust++rust+x=/tmp/fake",
            "--override_repository",
            "--override_module=rules_rust=/x",
            "--inject_repository=a=b",
            "--extra_toolchains=//tc:all",
            "--registry=https://evil",
            "--lockfile_mode=update",
            "--noenable_bzlmod",
            "--enable_bzlmod=false",
            "--enable_workspace",
            "--vendor_dir=v",
            "--repository_cache=/x",
            "--distdir=/x",
            "--@rules_rust//rust/toolchain/channel=nightly",
            "--@@rules_rust+//rust/toolchain/channel=nightly",
        ):
            self.assertIsNotNone(bl.refusal(arg), arg)

    def test_project_options_stay_allowed(self):
        for arg in (
            "--enable_bzlmod",
            "--noenable_workspace",
            "--config=lint",
            "--platforms=//platforms:aarch64_none",
            "--test_env=PATH",
            "--java_runtime_version=remotejdk_21",
            "--@rules_rust//rust/settings:clippy_flags=-A,warnings",  # the launcher's later value wins
            "//crates/...",
            "-c",
        ):
            self.assertIsNone(bl.refusal(arg), arg)

    def test_run_program_arguments_after_double_dash_are_not_bazel_options(self):
        self.assertEqual(bl.scan_args(["//x:y", "--", "--override_repository=a=b"]), [])
        self.assertEqual(len(bl.scan_args(["--override_repository=a=b", "//x"])), 1)


class RcScan(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.p = Path(self.td.name)

    def tearDown(self):
        self.td.cleanup()

    def test_every_section_config_import_and_continuation(self):
        (self.p / "user.bazelrc").write_text("build:x --extra_toolchains=//tc:all\n")
        (self.p / "more.bazelrc").write_text("import %workspace%/.bazelrc\ncommon --registry=https://r\n")
        (self.p / ".bazelrc").write_text(
            "# common --override_repository=commented=out\n"
            "common --enable_bzlmod\n"
            "build:ci --test_env=PATH \\\n"
            "    --override_repository=rules_rust++rust+t=/fake\n"
            "try-import %workspace%/user.bazelrc\n"
            "try-import %workspace%/absent.bazelrc\n"
            "import %workspace%/more.bazelrc\n"
            "test --override_module rules_rust=/x\n"
        )
        files, findings = bl.scan_rc(self.p)
        self.assertEqual(len(files), 3)  # the cycle back to .bazelrc is read once
        got = sorted((Path(f["file"]).name, f["line"], f["option"].split("=")[0]) for f in findings)
        self.assertEqual(
            got,
            [
                (".bazelrc", 3, "--override_repository"),
                (".bazelrc", 8, "--override_module"),
                ("more.bazelrc", 2, "--registry"),
                ("user.bazelrc", 1, "--extra_toolchains"),
            ],
        )

    def test_no_rc_file(self):
        self.assertEqual(bl.scan_rc(self.p), ([], []))


class EffectiveArguments(unittest.TestCase):
    def test_launcher_options_follow_the_users_and_precede_double_dash(self):
        a = bl.argv(
            "bazel",
            "test",
            ["--config=x", "//a/...", "--", "-//a/b"],
            Path("/c/rr"),
            Path("/c/p.bazelrc"),
            places=bl.Places(Path("/o"), Path("/rc")),
        )
        self.assertEqual(
            a[:6],
            [
                "bazel",
                "--nohome_rc",
                "--nosystem_rc",
                "--bazelrc=/c/p.bazelrc",
                "--output_user_root=/o",
                "test",
            ],
        )
        self.assertEqual(a[6:8], ["--config=x", "//a/..."])
        tail = a[8 : a.index("--")]
        self.assertEqual(tail[0], "--override_module=rules_rust=/c/rr")
        self.assertIn("--lockfile_mode=error", tail)
        self.assertIn("--repository_cache=/rc", tail)
        self.assertIn(f"--extra_toolchains={bl.TOOLCHAINS}", tail)
        self.assertIn("--@@rules_rust+//rust/settings:clippy_flags=-D,warnings", tail)
        self.assertEqual(a[a.index("--") :], ["--", "-//a/b"])

    def test_lint_is_a_build_with_both_aspects_and_query_has_no_build_options(self):
        lint = bl.argv("bazel", "lint", ["//..."], Path("/rr"), Path("/rc"), bep=Path("/b.json"))
        self.assertEqual(lint[4], "build")
        self.assertIn(f"--aspects={','.join(bl.ASPECTS)}", lint)
        self.assertIn("--output_groups=clippy_checks,rustfmt_checks", lint)
        self.assertEqual(lint[-1], "--build_event_json_file=/b.json")
        q = bl.argv("bazel", "query", ["//..."], Path("/rr"), Path("/rc"))
        self.assertFalse(any(x.startswith("--extra_toolchains") for x in q))
        self.assertIn("--lockfile_mode=error", q)

    def test_bazelisk_is_held_to_the_release(self):
        env = bl.bazel_env(MANIFEST, PROFILE, {"USE_BAZEL_VERSION": "7.0.0", "PATH": "/bin"})
        self.assertEqual(env["USE_BAZEL_VERSION"], MANIFEST["profiles"][PROFILE]["tools"]["bazel"]["version"])
        self.assertEqual(env["BAZELISK_SKIP_WRAPPER"], "true")
        self.assertIn("BAZELISK_VERIFY_SHA256", env)


class OverlayTest(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.cache = Path(self.td.name)

    def tearDown(self):
        self.td.cleanup()

    def test_derived_overlay_declares_and_enforces_the_release_toolchain(self):
        src = FakeSources()
        ov = bl.ensure_overlay(src.manifest(), PROFILE, "0.17.0", self.cache, fetch=src.fetch)
        mod = (ov.path / "MODULE.bazel").read_text()
        version = MANIFEST["profiles"][PROFILE]["tools"]["rust-toolchain"]["version"]
        self.assertIn(f'versions = ["{version}"]', mod)
        self.assertIn('extra_target_triples = ["aarch64-unknown-none-softfloat"]', mod)
        self.assertNotIn('rust.toolchain(edition = "2021")\n', mod)
        ext = (ov.path / "rust" / "extensions.bzl").read_text()
        self.assertIn("toolchains = rules_rust.tags.toolchain\n", ext)
        self.assertIn("differs from the verified toolchain", ext)
        self.assertIn("edition = root_edition or toolchain.edition", ext)
        self.assertNotIn("root.tags.toolchain or rules_rust.tags.toolchain", ext)
        build = (ov.path / "dev_platform" / "BUILD.bazel").read_text()
        self.assertIn('name = "aarch64_none"', build)
        self.assertTrue((ov.path / "dev_platform" / "rustfmt.toml").is_file())
        self.assertFalse(ov.repaired)

    def test_cache_is_reused_only_while_it_equals_a_fresh_derivation(self):
        src = FakeSources()
        m = src.manifest()
        first = bl.ensure_overlay(m, PROFILE, "0.17.0", self.cache, fetch=src.fetch)
        n = len(src.fetched)
        again = bl.ensure_overlay(m, PROFILE, "0.17.0", self.cache, fetch=src.fetch)
        self.assertEqual((again.path, again.digest, again.repaired), (first.path, first.digest, False))
        self.assertEqual(len(src.fetched), n, "verified downloads are reused")
        ext = first.path / "rust" / "extensions.bzl"
        ext.write_text(ext.read_text().replace("fail(", "print("))  # tampered cache
        repaired = bl.ensure_overlay(m, PROFILE, "0.17.0", self.cache, fetch=src.fetch)
        self.assertTrue(repaired.repaired)
        self.assertEqual(repaired.digest, first.digest)
        self.assertIn("fail(", ext.read_text())

    def test_tampered_download_is_fetched_again(self):
        src = FakeSources()
        m = src.manifest()
        bl.ensure_overlay(m, PROFILE, "0.17.0", self.cache, fetch=src.fetch)
        arc = next((self.cache / "bazel" / "downloads").glob("*.tar.gz"))
        arc.write_bytes(b"not the archive")
        n = len(src.fetched)
        bl.ensure_overlay(m, PROFILE, "0.17.0", self.cache, fetch=src.fetch)
        self.assertEqual(len(src.fetched), n + 1)

    def test_source_json_other_than_the_pinned_one_is_refused(self):
        src = FakeSources()
        m = src.manifest()
        bl.rules_rust_pin(m, PROFILE)["source_json_sha256"] = "0" * 64
        with self.assertRaises(ConfigError):
            bl.ensure_overlay(m, PROFILE, "0.17.0", self.cache, fetch=src.fetch)

    def test_unqualified_rules_rust_source_fails_closed(self):
        src = FakeSources(
            {"MODULE.bazel": FAKE_MODULE, "rust/extensions.bzl": "def _rust_impl(m):\n    pass\n"}
        )
        with self.assertRaises(ConfigError) as e:
            bl.ensure_overlay(src.manifest(), PROFILE, "0.17.0", self.cache, fetch=src.fetch)
        self.assertIn("not the one the platform's overlay is qualified for", str(e.exception.problems))

    def test_registry_patches_are_not_silently_dropped(self):
        src = FakeSources(extra={"patches": {"a.patch": "sha256-x"}})
        with self.assertRaises(ConfigError):
            bl.ensure_overlay(src.manifest(), PROFILE, "0.17.0", self.cache, fetch=src.fetch)


def _bep(*events: dict) -> list[str]:
    return [json.dumps(e) for e in events]


def _conf(label, kind, tags=None):
    return {
        "id": {"targetConfigured": {"label": label}},
        "configured": {"targetKind": f"{kind} rule", "tag": tags or []},
    }


def _aspect(label, aspect, set_id=None, success=True):
    group = "clippy_checks" if "clippy" in aspect else "rustfmt_checks"
    completed = {"success": True} if success else {}
    if set_id is not None:
        completed["outputGroup"] = [{"name": group, "fileSets": [{"id": set_id}]}]
    return {
        "id": {"targetCompleted": {"label": label, "aspect": f"@@rules_rust+//rust/private:{aspect}"}},
        "completed": completed,
    }


def _set(set_id, n=1):
    return {
        "id": {"namedSet": {"id": set_id}},
        "namedSetOfFiles": {"files": [{"name": f"f{i}"} for i in range(n)]},
    }


CLIPPY, FMT = "clippy.bzl%rust_clippy_aspect", "rustfmt.bzl%rustfmt_aspect"


class LintEvidence(unittest.TestCase):
    def test_classification(self):
        lines = _bep(
            _set("1"),
            _set("2"),
            _set("3"),
            _conf("//a:lib", "rust_library"),
            _aspect("//a:lib", CLIPPY, "1"),
            _aspect("//a:lib", FMT, "2"),
            _conf("//a:gen", "rust_library"),
            _aspect("//a:gen", CLIPPY, "3"),
            _aspect("//a:gen", FMT),
            _conf("//k:kernel", "rust_binary"),
            {"id": {"targetCompleted": {"label": "//k:kernel"}}, "aborted": {"reason": "SKIPPED"}},
            _conf("//a:quiet", "rust_test", ["no_clippy", "norustfmt"]),
            _conf("//a:bad", "rust_library"),
            _aspect("//a:bad", CLIPPY, success=False),
            _conf("//a:files", "filegroup"),
            _conf("//a:late", "rust_library"),
        )
        out = bl.lint_outcome(lines)
        t = out["targets"]
        self.assertNotIn("//a:files", t)
        self.assertEqual(
            (t["//a:lib"]["clippy_checks"], t["//a:lib"]["rustfmt_checks"]), ("checked", "checked")
        )
        self.assertEqual(t["//k:kernel"]["clippy_checks"], "skipped")
        self.assertEqual(t["//a:quiet"]["clippy_checks"], "opted-out")
        self.assertEqual(t["//a:bad"]["clippy_checks"], "failed")
        self.assertEqual(t["//a:late"]["clippy_checks"], "not-run")
        self.assertEqual(t["//a:gen"]["rustfmt_checks"], "empty")
        problems = bl.lint_problems(out, has_sources=lambda label: False)
        self.assertEqual(problems, [])
        self.assertEqual(t["//a:gen"]["rustfmt_checks"], "no-source")

    def test_empty_result_with_sources_is_unacceptable(self):
        out = bl.lint_outcome(
            _bep(
                _set("1"),
                _conf("//a:x", "rust_library"),
                _aspect("//a:x", CLIPPY, "1"),
                _aspect("//a:x", FMT),
            )
        )
        problems = bl.lint_problems(out, has_sources=lambda label: True)
        self.assertEqual(len(problems), 2)  # //a:x unchecked; and no rustfmt check anywhere
        self.assertEqual(out["targets"]["//a:x"]["rustfmt_checks"], "unchecked")

    def test_a_run_that_checked_nothing_fails(self):
        # the false green of #190: the aspects returned nothing for every target (external repository)
        out = bl.lint_outcome(
            _bep(_conf("//a:x", "rust_library"), _aspect("//a:x", CLIPPY), _aspect("//a:x", FMT))
        )
        problems = bl.lint_problems(out, has_sources=lambda label: True)
        self.assertTrue(any("no applicable Rust target was checked" in p for p in problems))
        self.assertTrue(bl.lint_problems(bl.lint_outcome([]), has_sources=lambda label: True))


class Audit(unittest.TestCase):
    AQ = json.dumps(
        {
            "actions": [
                {
                    "mnemonic": "Rustc",
                    "arguments": [
                        "pw",
                        "--",
                        "bazel-out/x/bin/external/rules_rust++rust+rust_macos_aarch64__aarch64-apple-darwin__stable_tools/rust_toolchain/bin/rustc",
                    ],
                },
            ]
        }
    )

    def _query(self, sub):
        if sub[0] == "aquery":
            return _cp(0, self.AQ)
        return _cp(0, "/exec/root\n")

    def test_version_is_read_from_the_binary(self):
        ok = bl.audit_rustc(self._query, ["//..."], [], "1.99.1", run_rustc=lambda p: "rustc 1.99.1 (x)")
        self.assertEqual(ok["problems"], [])
        # a replaced repository keeps the platform's name; only the binary tells (#190)
        bad = bl.audit_rustc(self._query, ["//..."], [], "1.99.1", run_rustc=lambda p: "rustc 1.98.0 (x)")
        self.assertEqual(len(bad["problems"]), 1)
        self.assertIn("1.98.0", bad["problems"][0])

    def test_rustc_outside_the_platform_repositories(self):
        self.AQ = json.dumps(
            {"actions": [{"mnemonic": "Rustc", "arguments": ["external/evil_rust/bin/rustc"]}]}
        )
        rec = bl.audit_rustc(self._query, ["//..."], [], "1.99.1", run_rustc=lambda p: "rustc 1.99.1")
        self.assertTrue(any("not a platform toolchain repository" in p for p in rec["problems"]))


class Execute(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        base = Path(self.td.name)
        self.project, self.cache = base / "proj", base / "cache"
        self.project.mkdir()
        (self.project / "MODULE.bazel").write_text('module(name = "p")\n')
        (self.project / "MODULE.bazel.lock").write_text("{}\n")
        self.src = FakeSources()
        self.calls: list[list[str]] = []

    def tearDown(self):
        self.td.cleanup()

    def _run(self, argv, *, cwd, env, capture=True):
        self.calls.append(argv)
        if argv[-1] == "--version":
            return _cp(0, f"bazel {env['USE_BAZEL_VERSION']}\n")
        return _cp(0, "")

    def _execute(self, args=("//...",), **kw):
        return bl.execute(
            project=self.project,
            command=kw.pop("command", "build"),
            args=list(args),
            manifest=self.src.manifest(),
            profile=PROFILE,
            release="0.17.0",
            cache=self.cache,
            run=kw.pop("run", self._run),
            fetch=self.src.fetch,
            base_env={"PATH": "/bin"},
            **kw,
        )

    def test_verified_run(self):
        code, rec = self._execute()
        self.assertEqual(code, 0)
        self.assertTrue(rec["verified"])
        self.assertEqual(rec["lockfile"]["sha256_before"], rec["lockfile"]["sha256_after"])
        self.assertIn(f"--extra_toolchains={bl.TOOLCHAINS}", rec["argv"])

    def test_refusals_happen_before_bazel_runs(self):
        (self.project / ".bazelrc").write_text(
            "common --override_repository=rules_rust++rust+rust_macos_aarch64__aarch64-apple-darwin__stable_tools=/fake\n"
        )
        with self.assertRaises(ConfigError) as e:
            self._execute()
        self.assertIn("override_repository", "\n".join(e.exception.problems))
        self.assertEqual(self.calls, [])
        (self.project / ".bazelrc").unlink()
        with self.assertRaises(ConfigError):
            self._execute(["--extra_toolchains=//evil:all", "//..."])
        self.assertEqual(self.calls, [])

    def test_missing_lockfile_is_refused(self):
        (self.project / "MODULE.bazel.lock").unlink()
        with self.assertRaises(ConfigError) as e:
            self._execute()
        self.assertIn("--lockfile_mode=update", "\n".join(e.exception.problems))

    def test_other_bazel_version_is_refused(self):
        def run(argv, *, cwd, env, capture=True):
            return _cp(0, "bazel 8.0.0\n")

        with self.assertRaises(ConfigError):
            self._execute(run=run)

    def test_changed_lockfile_or_failed_bazel_is_not_verified(self):
        lock = self.project / "MODULE.bazel.lock"

        def run(argv, *, cwd, env, capture=True):
            if argv[-1] == "--version":
                return _cp(0, f"bazel {env['USE_BAZEL_VERSION']}\n")
            lock.write_text('{"changed": true}\n')
            return _cp(0, "")

        code, rec = self._execute(run=run)
        self.assertEqual(code, 1)
        self.assertFalse(rec["verified"])

        def failing(argv, *, cwd, env, capture=True):
            return _cp(0, f"bazel {env['USE_BAZEL_VERSION']}\n") if argv[-1] == "--version" else _cp(3)

        lock.write_text("{}\n")
        code, rec = self._execute(run=failing)
        self.assertEqual((code, rec["verified"]), (3, False))

    def test_lint_without_any_result_is_not_verified(self):
        code, rec = self._execute(command="lint")  # the fake Bazel writes no BEP: nothing was checked
        self.assertEqual(code, 1)
        self.assertFalse(rec["verified"])
        self.assertTrue(any("no applicable Rust target was checked" in p for p in rec["problems"]))

    def test_project_must_be_its_own_root_module(self):
        (self.project / "MODULE.bazel").unlink()
        with self.assertRaises(ConfigError):
            self._execute()


if __name__ == "__main__":
    unittest.main()
