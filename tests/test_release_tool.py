"""tools/release.py: the parts that decide what a release contains (GitHub and git are not called here)."""

import importlib.util
import json
import re
import shutil
import subprocess
import unittest

from dev_platform import planning
from tests.helpers import ROOT, tmpdir

spec = importlib.util.spec_from_file_location("release_tool", ROOT / "tools" / "release.py")
R = importlib.util.module_from_spec(spec)
spec.loader.exec_module(R)
POLICY = planning.load_policy(ROOT / "planning" / "release-policy.json")
PRED = {"version": "0.11.0", "archive_sha256": "a" * 64, "tree_digest": "b" * 64}
CHANGELOG = "# Changelog\n\n## Unreleased\nAdded: a thing.\n\n## 0.11.0 (old)\nOld notes.\n"


def has_tag(tag: str) -> bool:
    return subprocess.run(["git", "-C", str(ROOT), "rev-parse", "-q", "--verify", f"{tag}^{{commit}}"],
                          capture_output=True).returncode == 0  # fmt: skip


class Versions(unittest.TestCase):
    def test_smallest_version_the_policy_allows(self):
        self.assertEqual(R.next_version("0.11.0", [], POLICY), "0.11.1")
        self.assertEqual(R.next_version("0.11.0", ["bugfix"], POLICY), "0.11.1")
        self.assertEqual(R.next_version("0.11.0", ["feature", "bugfix"], POLICY), "0.12.0")
        self.assertEqual(R.next_version("0.11.0", ["schema-added"], POLICY), "0.12.0")
        self.assertEqual(
            R.next_version("0.11.0", ["breaking-config"], POLICY), "0.12.0"
        )  # 0.x: declared minor


class Notes(unittest.TestCase):
    def test_unreleased_notes_move_under_the_version(self):
        out = R.changelog_release(CHANGELOG, "0.12.0")
        self.assertEqual(
            out, "# Changelog\n\n## Unreleased\n\n## 0.12.0\nAdded: a thing.\n\n## 0.11.0 (old)\nOld notes.\n"
        )

    def test_empty_notes_or_an_existing_section_block(self):
        with self.assertRaisesRegex(R.Stop, "empty"):
            R.changelog_release("## Unreleased\n\n## 0.11.0\nx\n", "0.12.0")
        with self.assertRaisesRegex(R.Stop, "already"):
            R.changelog_release(CHANGELOG, "0.11.0")
        with self.assertRaisesRegex(R.Stop, "no `## Unreleased`"):
            R.changelog_release("# Changelog\n", "0.12.0")


class Prepare(unittest.TestCase):
    def tree(self, changelog=CHANGELOG):
        d = tmpdir(self)
        for p in ("src/dev_platform/__init__.py", "trust/policy.json"):
            (d / p).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / p, d / p)
        # the repository's own version and predecessor move with every release; the fixture must not
        init = d / "src/dev_platform/__init__.py"
        init.write_text(re.sub(r'__version__ = "[^"]*"', '__version__ = "0.11.0"', init.read_text()))
        pol = json.loads((d / "trust/policy.json").read_text())
        pol["continuity"]["predecessor"] = {
            "version": "0.10.0",
            "archive_sha256": "c" * 64,
            "tree_digest": "d" * 64,
        }
        (d / "trust/policy.json").write_text(json.dumps(pol, indent=2) + "\n")
        (d / "CHANGELOG.md").write_text(changelog)
        return d

    def test_version_predecessor_and_notes(self):
        d = self.tree()
        self.assertFalse(R.is_prepared(d, "0.12.0", PRED))
        R.prepare(d, "0.12.0", PRED)
        self.assertTrue(R.is_prepared(d, "0.12.0", PRED))
        self.assertIn('__version__ = "0.12.0"', (d / "src/dev_platform/__init__.py").read_text())
        pol = json.loads((d / "trust/policy.json").read_text())
        self.assertEqual(pol["continuity"]["predecessor"], PRED)
        self.assertEqual(pol["schema"], "dev-platform.trust/v2")  # everything else is kept
        self.assertIn("## 0.12.0\nAdded: a thing.", (d / "CHANGELOG.md").read_text())

    def test_a_blocker_writes_nothing(self):
        d = self.tree("## Unreleased\n\n## 0.11.0\nx\n")
        before = {p: (d / p).read_bytes() for p in R.PREPARED}
        with self.assertRaises(R.Stop):
            R.prepare(d, "0.12.0", PRED)
        self.assertEqual({p: (d / p).read_bytes() for p in R.PREPARED}, before)


class Records(unittest.TestCase):
    """The generated identity is what consumers, setup, consumer_run.py, the formula and the tap rely on."""

    REL = ROOT / "releases" / "0.10.0"

    @unittest.skipUnless(has_tag("v0.10.0"), "needs the v0.10.0 tag")
    def test_verifier_pins_reproduce_a_recorded_identity(self):
        ident = json.loads((self.REL / "identity.json").read_text())
        rev = ident["source_revision"]
        pins = R.verifier_pins(lambda p: subprocess.run(["git", "-C", str(ROOT), "show", f"{rev}:{p}"],
                                                        capture_output=True, check=True).stdout)  # fmt: skip
        self.assertEqual(pins, ident["verifier_pins"])

    def test_identity_from_the_release_records_matches_the_recorded_one(self):
        ident = json.loads((self.REL / "identity.json").read_text())
        ci = json.loads((self.REL / "verification.ci.json").read_text())
        cont = json.loads((self.REL / "continuity.json").read_text())
        made = R.identity("0.10.0", ident["source_revision"], ci, cont, ident["github_release"],
                          ident["release_workflow_run"], ident["verifier_pins"])  # fmt: skip
        for k in ("version", "git_tag", "source_revision", "archive", "archive_sha256", "tree_digest_pin",
                  "release_workflow_run", "signer", "github_release", "verifier_pins", "continuity"):  # fmt: skip
            self.assertEqual(made[k], ident[k], k)
        self.assertEqual(made["state"], "verified-unaccepted")  # taken from the record, never reinterpreted

    def test_the_formula_renders_from_a_generated_identity(self):
        ident = json.loads((self.REL / "identity.json").read_text())
        f = tmpdir(self) / "identity.json"
        f.write_text(json.dumps(ident))
        spec = importlib.util.spec_from_file_location("hf", ROOT / "tools" / "homebrew_formula.py")
        hf = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(hf)
        self.assertEqual(hf.from_identity(f), (self.REL / "homebrew" / "dev-platform.rb").read_text())


class Verdict(unittest.TestCase):
    def test_ready_and_blocked(self):
        ok = {
            "ready": True,
            "version": "0.12.0",
            "previous": "0.11.0",
            "commit": "c" * 40,
            "checks": ["unit tests"],
        }
        self.assertTrue(R.verdict(ok).startswith("READY TO RELEASE — v0.12.0 (after 0.11.0"))
        bad = {"ready": False, "problems": ["unit tests: 2 failed"], "checks": []}
        self.assertEqual(R.verdict(bad), "BLOCKED\n  - unit tests: 2 failed")


if __name__ == "__main__":
    unittest.main()
