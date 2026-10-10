import unittest

from dev_platform import closure as C
from dev_platform import toolchain as T
from dev_platform.errors import ConfigError
from tests.helpers import tmpdir

PROBE = {"argv": ["tool", "--version"], "pattern": "tool (\\S+)"}
MANIFEST = {
    "schema": T.SCHEMA,
    "profiles": {
        "p": {"tools": {"tool": {"version": "1.2.3", "probe": PROBE}}},
        "bz": {
            "tools": {
                "bazel": {
                    "version": "8.1.0",
                    "bazel_managed": True,
                    "declared_in": {"file": ".bazelversion", "pattern": "(\\S+)"},
                }
            }
        },
    },
}


def probe_returning(text, code=0):
    return lambda argv: (code, text)


class ToolchainTest(unittest.TestCase):
    def test_validate_rejects_bad_manifests(self):
        for bad in (
            {},
            {"schema": T.SCHEMA},
            {"schema": T.SCHEMA, "profiles": {"p": {"tools": {"t": {}}}}},
            {"schema": T.SCHEMA, "profiles": {"p": {"tools": {"t": {"version": "1"}}}}},
            {
                "schema": T.SCHEMA,
                "profiles": {
                    "p": {"tools": {"t": {"version": "1", "probe": {"argv": ["t"], "pattern": "nogroup"}}}}
                },
            },
            {
                "schema": T.SCHEMA,
                "profiles": {"p": {"tools": {"t": {"version": "1", "bazel_managed": True}}}},
            },
        ):
            with self.assertRaises(ConfigError):
                T.validate(bad)

    def test_conformant_environment(self):
        rec = T.verify_profile(MANIFEST, "p", tmpdir(self), probe_returning("tool 1.2.3"))
        self.assertTrue(rec["conformant"])
        self.assertEqual(rec["tools"][0]["identity"], "version-only")

    def test_substituted_tool_version_is_not_conformant(self):
        rec = T.verify_profile(MANIFEST, "p", tmpdir(self), probe_returning("tool 1.2.4"))
        self.assertFalse(rec["conformant"])
        self.assertEqual(rec["tools"][0]["status"], "mismatch")

    def test_missing_tool_is_unavailable_not_conformant(self):
        rec = T.verify_profile(MANIFEST, "p", tmpdir(self), probe_returning("", 127))
        self.assertEqual(rec["tools"][0]["status"], "unavailable")
        self.assertFalse(rec["conformant"])

    def test_identity_digest_tracks_observed_tools(self):
        a = T.verify_profile(MANIFEST, "p", tmpdir(self), probe_returning("tool 1.2.3"))
        b = T.verify_profile(MANIFEST, "p", tmpdir(self), probe_returning("tool 1.2.3"))
        c = T.verify_profile(MANIFEST, "p", tmpdir(self), probe_returning("tool 9"))
        self.assertEqual(a["identity_digest"], b["identity_digest"])
        self.assertNotEqual(a["identity_digest"], c["identity_digest"])

    def test_unknown_profile(self):
        with self.assertRaisesRegex(ConfigError, "not defined by this platform release"):
            T.verify_profile(MANIFEST, "nope", tmpdir(self))

    def test_bazel_managed_declarations_are_reconciled_not_executed(self):
        d = tmpdir(self)

        def boom(argv):
            raise AssertionError("must not execute compilers/bazel")

        (d / ".bazelversion").write_text("8.1.0\n")
        self.assertTrue(T.verify_profile(MANIFEST, "bz", d, boom)["conformant"])
        (d / ".bazelversion").write_text("8.2.0\n")
        rec = T.verify_profile(MANIFEST, "bz", d, boom)
        self.assertEqual((rec["conformant"], rec["tools"][0]["status"]), (False, "mismatch"))
        (d / ".bazelversion").unlink()
        self.assertEqual(T.verify_profile(MANIFEST, "bz", d, boom)["tools"][0]["status"], "unreconciled")

    def test_prefix_compare_is_explicit(self):
        m = {
            "schema": T.SCHEMA,
            "profiles": {
                "p": {
                    "tools": {
                        "py": {
                            "version": "3.14.",
                            "compare": "prefix",
                            "probe": {"argv": ["x"], "pattern": "(\\S+)"},
                        }
                    }
                }
            },
        }
        self.assertTrue(T.verify_profile(m, "p", tmpdir(self), probe_returning("3.14.6"))["conformant"])
        self.assertFalse(T.verify_profile(m, "p", tmpdir(self), probe_returning("3.15.0"))["conformant"])

    def test_binary_digest_mismatch_detected(self):
        import sys

        m = {
            "schema": T.SCHEMA,
            "profiles": {
                "p": {
                    "tools": {
                        "py": {
                            "version": "1",
                            "sha256": "0" * 64,
                            "probe": {"argv": ["{python}", "--version"], "pattern": "(\\d)"},
                        }
                    }
                }
            },
        }
        rec = T.verify_profile(m, "p", tmpdir(self), probe_returning("1"))
        self.assertEqual((rec["tools"][0]["identity"], rec["tools"][0]["status"]), ("none", "mismatch"))
        self.assertTrue(sys.executable)


if __name__ == "__main__":
    unittest.main()


SHA_A = "a" * 64
SHA_B = "b" * 64
BAZEL_LOCKED = {
    "schema": T.SCHEMA,
    "profiles": {
        "bz": {
            "tools": {
                "rules_rust_toolchain": {
                    "version": "8.1.0",
                    "bazel_managed": True,
                    "declared_in": {"file": ".bazelversion", "pattern": "(\\S+)"},
                    "integrity": [
                        {
                            "name": "rustc",
                            "file": "MODULE.bazel",
                            "pattern": 'sha256 = "([0-9a-f]{64})"',
                            "sha256": SHA_A,
                            "lock_file": "MODULE.bazel.lock",
                        }
                    ],
                }
            }
        }
    },
}


def bazel_consumer(test, declared=SHA_A, lock=SHA_A, version="8.1.0"):
    d = tmpdir(test)
    (d / ".bazelversion").write_text(version + "\n")
    (d / "MODULE.bazel").write_text(f'rust.toolchain(sha256 = "{declared}")\n')
    if lock is not None:
        (d / "MODULE.bazel.lock").write_text(f'{{"rustc": "{lock}"}}')
    return d


class IdentityStrengthTest(unittest.TestCase):
    def test_probe_without_pinned_digest_is_never_stronger_than_version_only(self):
        rec = T.verify_profile(MANIFEST, "p", tmpdir(self), probe_returning("tool 1.2.3"))
        self.assertEqual(rec["tools"][0]["identity"], "version-only")
        self.assertEqual(
            (rec["conformant"], rec["assurance"], rec["weak_tools"]), (True, "diagnostic", ["tool"])
        )

    def test_binary_digest_alone_is_not_certifiable(self):
        import hashlib
        import sys
        from pathlib import Path

        real = hashlib.sha256(Path(sys.executable).resolve().read_bytes()).hexdigest()
        spec = {
            "version": "3",
            "compare": "prefix",
            "sha256": real,
            "probe": {"argv": ["{python}", "--version"], "pattern": "Python (\\S+)"},
        }
        m = {"schema": T.SCHEMA, "profiles": {"p": {"tools": {"py": spec}}}}
        rec = T.verify_profile(m, "p", tmpdir(self))
        self.assertEqual((rec["tools"][0]["identity"], rec["assurance"]), ("digest-verified", "diagnostic"))
        spec["sha256"] = "0" * 64
        rec = T.verify_profile(m, "p", tmpdir(self))
        self.assertEqual((rec["tools"][0]["identity"], rec["assurance"]), ("none", "diagnostic"))
        self.assertFalse(rec["conformant"])

    def test_unavailable_tool_claims_nothing(self):
        rec = T.verify_profile(MANIFEST, "p", tmpdir(self), probe_returning("", 127))
        self.assertEqual(rec["tools"][0]["identity"], "none")

    def test_bazel_declared_is_weak_and_locked_is_strong(self):
        d = tmpdir(self)
        (d / ".bazelversion").write_text("8.1.0\n")
        rec = T.verify_profile(MANIFEST, "bz", d)
        self.assertEqual((rec["tools"][0]["identity"], rec["assurance"]), ("bazel-declared", "diagnostic"))
        rec = T.verify_profile(BAZEL_LOCKED, "bz", bazel_consumer(self))
        self.assertEqual((rec["tools"][0]["identity"], rec["assurance"]), ("bazel-locked", "certifiable"))
        self.assertEqual(rec["tools"][0]["integrity"][0]["status"], "ok")

    def test_bazel_integrity_failures_never_claim_identity(self):
        cases = {
            "declared digest differs": bazel_consumer(self, declared=SHA_B),
            "absent from resolved graph": bazel_consumer(self, lock=SHA_B),
            "no lock file": bazel_consumer(self, lock=None),
            "wrong bazel version": bazel_consumer(self, version="8.0.0"),
        }
        for name, d in cases.items():
            rec = T.verify_profile(BAZEL_LOCKED, "bz", d)
            self.assertFalse(rec["conformant"], name)
            self.assertEqual(rec["tools"][0]["identity"], "none", name)
            self.assertEqual(rec["assurance"], "diagnostic", name)

    def test_bazel_checks_never_execute_host_tools(self):
        def boom(argv):
            raise AssertionError("host executable must not be consulted")

        self.assertTrue(T.verify_profile(BAZEL_LOCKED, "bz", bazel_consumer(self), boom)["conformant"])

    def test_manifest_cannot_assert_strength(self):
        m = {
            "schema": T.SCHEMA,
            "profiles": {
                "p": {
                    "tools": {
                        "t": {
                            "version": "1",
                            "identity": "digest-verified",
                            "probe": {"argv": ["t"], "pattern": "(\\d)"},
                        }
                    }
                }
            },
        }
        rec = T.verify_profile(m, "p", tmpdir(self), probe_returning("1"))
        self.assertEqual(rec["tools"][0]["identity"], "version-only")

    def test_integrity_entries_are_validated(self):
        bad = {
            "schema": T.SCHEMA,
            "profiles": {
                "p": {
                    "tools": {
                        "t": {
                            "version": "1",
                            "bazel_managed": True,
                            "declared_in": {"file": "f", "pattern": "(x)"},
                            "integrity": [{"name": "n"}],
                        }
                    }
                }
            },
        }
        with self.assertRaises(ConfigError):
            T.validate(bad)


def make_prefix(test, files=None):
    d = tmpdir(test) / "tool"
    (d / "bin").mkdir(parents=True)
    (d / "lib").mkdir()
    exe = d / "bin" / "tool"
    exe.write_bytes(b"\x7fELF" + b"exe")
    exe.chmod(0o755)
    (d / "lib" / "stdlib.txt").write_text("stdlib")
    (d / "bin" / "tool3").symlink_to("tool")
    return d


def closure_manifest(prefix, digest, libs=("libc.so.6",)):
    return {
        "schema": T.SCHEMA,
        "profiles": {
            "p": {
                "tools": {
                    "tool": {
                        "version": "1.2.3",
                        "executable": str(prefix / "bin" / "tool3"),
                        "probe": PROBE,
                        "closure": {
                            "kind": "prefix",
                            "prefix_up": 2,
                            "sha256": {C.platform_key(): digest},
                            "system_libs": list(libs),
                        },
                    }
                }
            }
        },
    }


class ClosureIdentityTest(unittest.TestCase):
    def setUp(self):
        self.prefix = make_prefix(self)
        self.digest = C.digest(self.prefix)[0]

    def run_profile(self, m, deps=("libc.so.6",)):
        return T.verify_profile(m, "p", tmpdir(self), probe_returning("tool 1.2.3"), lambda p: list(deps))

    def test_matching_closure_is_certifiable_and_scoped(self):
        rec = self.run_profile(closure_manifest(self.prefix, self.digest))
        t = rec["tools"][0]
        self.assertEqual((t["identity"], rec["assurance"]), ("closure-verified", "certifiable"))
        self.assertEqual(t["closure"]["files"], 3)
        self.assertIn("trusted by name, not by content", t["closure"]["scope"])

    def test_any_changed_byte_in_the_closure_fails(self):
        (self.prefix / "lib" / "stdlib.txt").write_text("stdlib!")
        rec = self.run_profile(closure_manifest(self.prefix, self.digest))
        self.assertEqual((rec["conformant"], rec["tools"][0]["identity"]), (False, "none"))

    def test_added_file_and_mode_change_fail(self):
        (self.prefix / "lib" / "extra.py").write_text("x")
        self.assertNotEqual(C.digest(self.prefix)[0], self.digest)
        (self.prefix / "lib" / "extra.py").unlink()
        self.assertEqual(C.digest(self.prefix)[0], self.digest)
        (self.prefix / "bin" / "tool").chmod(0o644)
        self.assertNotEqual(C.digest(self.prefix)[0], self.digest)

    def test_bytecode_caches_do_not_change_identity(self):
        (self.prefix / "lib" / "__pycache__").mkdir()
        (self.prefix / "lib" / "__pycache__" / "a.pyc").write_bytes(b"x")
        self.assertEqual(C.digest(self.prefix)[0], self.digest)

    def test_symlink_leaving_the_closure_is_rejected(self):
        (self.prefix / "lib" / "evil").symlink_to("../../outside")
        with self.assertRaises(ConfigError):
            C.digest(self.prefix)
        (self.prefix / "lib" / "evil").unlink()
        (self.prefix / "lib" / "abs").symlink_to("/etc/passwd")
        with self.assertRaises(ConfigError):
            C.digest(self.prefix)

    def test_native_dependency_outside_closure_fails(self):
        rec = self.run_profile(closure_manifest(self.prefix, self.digest), deps=("libevil.so",))
        self.assertEqual((rec["conformant"], rec["tools"][0]["identity"]), (False, "none"))
        self.assertIn("libevil.so", rec["tools"][0]["closure"]["linkage"]["violations"][0])

    def test_dependency_satisfied_inside_the_closure(self):
        (self.prefix / "lib" / "libown.so").write_bytes(b"data")
        digest = C.digest(self.prefix)[0]
        rec = self.run_profile(closure_manifest(self.prefix, digest), deps=("@rpath/libown.so",))
        self.assertEqual(rec["tools"][0]["identity"], "closure-verified")

    def test_unlistable_linkage_fails_closed(self):
        m = closure_manifest(self.prefix, self.digest)
        rec = T.verify_profile(m, "p", tmpdir(self), probe_returning("tool 1.2.3"), lambda p: None)
        self.assertEqual((rec["conformant"], rec["tools"][0]["identity"]), (False, "none"))

    def test_platform_without_a_pinned_digest_claims_only_the_version(self):
        m = closure_manifest(self.prefix, self.digest)
        m["profiles"]["p"]["tools"]["tool"]["closure"]["sha256"] = {"plan9-mips": self.digest}
        rec = self.run_profile(m)
        t = rec["tools"][0]
        self.assertEqual((t["identity"], t["closure"]["status"]), ("version-only", "unpinned"))
        self.assertEqual((rec["conformant"], rec["assurance"]), (True, "diagnostic"))

    def test_wrong_version_never_claims_closure(self):
        rec = T.verify_profile(
            closure_manifest(self.prefix, self.digest),
            "p",
            tmpdir(self),
            probe_returning("tool 9.9.9"),
            lambda p: [],
        )
        self.assertEqual(rec["tools"][0]["identity"], "none")

    def test_closure_spec_is_validated(self):
        m = closure_manifest(self.prefix, "xyz")
        m["profiles"]["p"]["tools"]["tool"]["closure"]["prefix_up"] = 0
        with self.assertRaises(ConfigError) as cm:
            T.validate(m)
        self.assertIn("prefix_up", str(cm.exception))
        self.assertIn("64 hex", str(cm.exception))
