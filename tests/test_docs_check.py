"""The documentation gate (`tools/check_docs.py`) runs in the unit tests too, so a malformed ADR (for example a
`Status:` value outside Ratified, Proposed and Superseded) fails here, before the full-stage self verification."""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.helpers import ROOT


class DocsGate(unittest.TestCase):
    def test_the_repository_documentation_passes(self):
        r = subprocess.run(
            [sys.executable, str(ROOT / "tools" / "check_docs.py")], capture_output=True, text=True
        )
        self.assertEqual((r.returncode, r.stderr), (0, ""))

    def test_an_adr_status_outside_the_vocabulary_is_refused(self):
        adr = ROOT / "docs" / "adr" / "0027-repository-isolation.md"
        text = adr.read_text()
        self.assertRegex(text, r"(?m)^Status: (Ratified|Proposed|Superseded)")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "docs" / "adr").mkdir(parents=True)
            (root / "tools").mkdir()
            (root / "schemas").mkdir()
            (root / "tools" / "check_docs.py").write_text((ROOT / "tools" / "check_docs.py").read_text())
            (root / "docs" / "adr" / "README.md").write_text("0099-x.md\n")
            (root / "docs" / "adr" / "0099-x.md").write_text("# 0099 x\n\nStatus: Accepted (owner)\n")
            r = subprocess.run(
                [sys.executable, str(root / "tools" / "check_docs.py")], capture_output=True, text=True
            )
            self.assertEqual(r.returncode, 1)
            self.assertIn("0099-x.md: missing 'Status:' line", r.stderr)


if __name__ == "__main__":
    unittest.main()
