"""The public repository, its release tree and its fixtures carry no private infrastructure data (ADR 0023).

Generic shapes are checked here: secret values, private network addresses, internal host names, non-synthetic
owners in infrastructure fixtures. An organization's own identifiers (runner ids, endpoints, credential references)
cannot be listed in a public test; its CI points `DEV_PLATFORM_PRIVATE_DENYLIST` at a file of them (one per line)
and this test then requires that no tracked file contains any. Without it that part is skipped, never passed.
"""

import json
import os
import re
import subprocess
import unittest
from pathlib import Path

from tests.helpers import ROOT, tmpdir

SECRETS = re.compile(
    r"gh[pousr]_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{22,}|-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]{20}"
    r"|AKIA[0-9A-Z]{16}\b|xox[baprs]-[0-9]{6,}-|://[^/\s:@\"'`]+:[^/\s@\"'`]{6,}@"
)
PRIVATE_NET = re.compile(
    r"\b(10\.\d{1,3}\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}|172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})\b"
)
INTERNAL_HOST = re.compile(r"\b[a-z0-9-]+(\.[a-z0-9-]+)*\.(internal|lan|corp|intranet|home\.arpa)\b", re.I)
SYNTHETIC_OWNERS = {"example-org", "my-org", "acme", "o", "owner", "someone", "someone-else"}


def tracked() -> list[Path]:
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True)
    if out.returncode != 0:
        raise unittest.SkipTest("not a git checkout")
    return [ROOT / p for p in out.stdout.splitlines() if (ROOT / p).is_symlink() or (ROOT / p).is_file()]


def texts(paths=None):
    """What is published for each tracked path: a file's content, or a symlink's target string (Git stores the
    target, whether or not it exists)."""
    for f in tracked() if paths is None else paths:
        if f.is_symlink():
            yield f, os.readlink(f)
            continue
        try:
            yield f, f.read_text()
        except UnicodeDecodeError:
            continue


class Shapes(unittest.TestCase):
    def test_no_secret_values(self):
        for f, text in texts():
            self.assertIsNone(SECRETS.search(text), f.relative_to(ROOT))

    def test_no_private_addresses_or_internal_hosts(self):
        for f, text in texts():
            rel = f.relative_to(ROOT).as_posix()
            if rel == "tests/test_public_boundary.py":
                continue
            self.assertIsNone(PRIVATE_NET.search(text), rel)
            self.assertIsNone(INTERNAL_HOST.search(text), rel)

    def test_symlink_targets_are_scanned(self):
        d = tmpdir(self)
        os.symlink("vpn.example.corp", d / "link")
        published = [t for _, t in texts([d / "link"])]
        self.assertEqual(published, ["vpn.example.corp"])
        self.assertIsNotNone(INTERNAL_HOST.search(published[0]))

    def test_infrastructure_fixtures_are_synthetic(self):
        for f in [*(ROOT / "examples").rglob("*.json"), *(ROOT / "contracts" / "infra").rglob("*.json")]:
            doc = json.loads(f.read_text())
            owner = doc.get("owner") if isinstance(doc, dict) else None
            self.assertTrue(owner is None or owner in SYNTHETIC_OWNERS, f)
        fixtures = (ROOT / "tests" / "infra_fixtures.py").read_text()
        self.assertIn('OWNER = "example-org"', fixtures)

    def test_release_tree_names_no_private_repository_content(self):
        # The package names the previous private release format (to resolve existing releases unchanged) and the
        # repository kind in prose; nothing else of a private repository.
        src = ROOT / "src" / "dev_platform"
        for p in sorted(src.glob("*.py")):
            text = p.read_text()
            self.assertNotRegex(text, r"syncom-systems/dev-platform-infra", p.name)


@unittest.skipUnless(os.environ.get("DEV_PLATFORM_PRIVATE_DENYLIST"), "no organization deny-list supplied")
class OrganizationDenyList(unittest.TestCase):
    def test_no_tracked_file_contains_a_listed_identifier(self):
        terms = [
            t.strip() for t in Path(os.environ["DEV_PLATFORM_PRIVATE_DENYLIST"]).read_text().splitlines()
        ]
        terms = [t for t in terms if t and not t.startswith("#")]
        self.assertTrue(terms, "the deny-list is empty")
        hits = [
            (f.relative_to(ROOT).as_posix(), i)
            for f, text in texts()
            for i, t in enumerate(terms)
            if t in text
        ]
        self.assertEqual(hits, [], "tracked files contain listed identifiers (file, term index)")


if __name__ == "__main__":
    unittest.main()
