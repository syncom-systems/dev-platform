import unittest

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
        self.assertEqual(
            (rec["tools"][0]["identity"], rec["tools"][0]["status"]), ("digest-verified", "mismatch")
        )
        self.assertTrue(sys.executable)


if __name__ == "__main__":
    unittest.main()
