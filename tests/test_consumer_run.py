"""consumer_run: the consumer's own pins must agree, and the trusted tools must equal the pinned digests."""

import hashlib
import importlib.util
import json
import subprocess
import unittest

from tests.helpers import ROOT, tmpdir

spec = importlib.util.spec_from_file_location("consumer_run", ROOT / "tools" / "consumer_run.py")
C = importlib.util.module_from_spec(spec)
spec.loader.exec_module(C)

TREE, ARCH, REV = "a" * 64, "b" * 64, "c" * 40
PINS = {
    "version": "0.8.0",
    "source_revision": REV,
    "archive_sha256": ARCH,
    "tree_digest_pin": TREE,
    "verifier_pins": {
        "verify_release.py_sha256": "1" * 64,
        "trust_policy_sha256": "2" * 64,
        "install_release.py_sha256": "3" * 64,
    },
}
TOML = f'schema_version = 1\n[platform]\nversion = "0.8.0"\nsha256 = "{TREE}"\nprofile = "rust-bazel-9"\n'


def consumer(test, pins=PINS, toml=TOML):
    d = tmpdir(test)
    (d / "dev-platform.toml").write_text(toml)
    if pins is not None:
        (d / C.PINS_FILE).write_text(json.dumps(pins))
    return d


class Pins(unittest.TestCase):
    def test_consistent(self):
        _, _, problems = C.read_pins(consumer(self))
        self.assertEqual(problems, [])

    def test_version_and_tree_must_agree_between_the_two_files(self):
        _, _, p = C.read_pins(consumer(self, pins={**PINS, "version": "0.7.0"}))
        self.assertTrue(any("version" in x for x in p))
        _, _, p = C.read_pins(consumer(self, pins={**PINS, "tree_digest_pin": "d" * 64}))
        self.assertTrue(any("tree_digest_pin" in x for x in p))

    def test_malformed_or_missing(self):
        bad = {**PINS, "source_revision": "main", "verifier_pins": {}}
        _, _, p = C.read_pins(consumer(self, pins=bad))
        self.assertTrue(any("source_revision" in x for x in p))
        self.assertTrue(any("verify_release.py_sha256" in x for x in p))
        _, _, p = C.read_pins(consumer(self, pins=None))
        self.assertTrue(p)

    def test_self_hosted_is_not_a_consumer(self):
        _, _, p = C.read_pins(consumer(self, toml="schema_version = 1\n[platform]\nself_hosted = true\n"))
        self.assertTrue(any("self-hosted" in x for x in p))


class Tools(unittest.TestCase):
    def repo(self):
        d = tmpdir(self)
        env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@i", "GIT_COMMITTER_NAME": "t",
               "GIT_COMMITTER_EMAIL": "t@i", "PATH": "/usr/bin:/bin:/opt/homebrew/bin"}  # fmt: skip
        files = {
            "tools/verify_release.py": "v\n",
            "trust/policy.json": "{}\n",
            "tools/install_release.py": "i\n",
        }
        for rel, text in files.items():
            (d / rel).parent.mkdir(parents=True, exist_ok=True)
            (d / rel).write_text(text)
        for cmd in (["init", "-q"], ["add", "-A"], ["commit", "-qm", "x"]):
            subprocess.run(["git", "-C", str(d), *cmd], env=env, check=True, capture_output=True)
        rev = subprocess.run(
            ["git", "-C", str(d), "rev-parse", "HEAD"], capture_output=True, text=True
        ).stdout.strip()
        pins = {**PINS, "source_revision": rev, "verifier_pins": {
            "verify_release.py_sha256": hashlib.sha256(b"v\n").hexdigest(),
            "trust_policy_sha256": hashlib.sha256(b"{}\n").hexdigest(),
            "install_release.py_sha256": hashlib.sha256(b"i\n").hexdigest()}}  # fmt: skip
        return d, pins

    def test_tools_equal_to_the_pins_are_accepted(self):
        d, pins = self.repo()
        tools_dir, why = C.pinned_tools(pins, tmpdir(self), "unused", d)
        self.assertIsNotNone(tools_dir, why)
        self.assertEqual((tools_dir / "tools" / "verify_release.py").read_text(), "v\n")

    def test_a_tool_that_differs_from_its_pin_is_refused(self):
        d, pins = self.repo()
        pins["verifier_pins"]["trust_policy_sha256"] = "9" * 64
        tools_dir, why = C.pinned_tools(pins, tmpdir(self), "unused", d)
        self.assertIsNone(tools_dir)
        self.assertIn("policy.json", why)

    def test_a_checkout_at_another_revision_is_refused(self):
        d, pins = self.repo()
        pins["source_revision"] = "f" * 40
        tools_dir, why = C.pinned_tools(pins, tmpdir(self), "unused", d)
        self.assertIsNone(tools_dir)
        self.assertIn("pinned revision", why)


class Trust(unittest.TestCase):
    def test_outside_ci_is_untrusted(self):
        self.assertEqual(C.event_trust({}), "untrusted")


if __name__ == "__main__":
    unittest.main()
