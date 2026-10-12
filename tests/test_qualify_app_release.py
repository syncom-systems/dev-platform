"""tools/qualify_app_release.py: the chain and its rejection cases over a (synthetic) certified result.

Real qualification runs it over a real build-system result in CI (`tools/qualify.py --app-release`); this keeps
the script itself honest where no compiler is available.
"""

import importlib.util
import json
import os
import subprocess
import unittest

from tests.helpers import ROOT, tmpdir
from tests.test_provenance import result

spec = importlib.util.spec_from_file_location(
    "qualify_app_release", ROOT / "tools" / "qualify_app_release.py"
)
Q = importlib.util.module_from_spec(spec)
spec.loader.exec_module(Q)


class Chain(unittest.TestCase):
    def test_every_case_behaves_as_expected(self):
        d = tmpdir(self)
        c = d / "consumer"
        c.mkdir()
        (c / "Cargo.lock").write_text("lock\n")
        (c / "main.rs").write_text("fn main(){}\n")
        genv = {**os.environ, "GIT_AUTHOR_NAME": "q", "GIT_AUTHOR_EMAIL": "q@x.invalid",
                "GIT_COMMITTER_NAME": "q", "GIT_COMMITTER_EMAIL": "q@x.invalid"}  # fmt: skip
        for cmd in (["init", "-q"], ["add", "-A"], ["commit", "-qm", "c"]):
            subprocess.run(["git", *cmd], cwd=c, env=genv, check=True, capture_output=True)
        rev = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=c, capture_output=True, text=True
        ).stdout.strip()
        rp = d / "result.json"
        rp.write_text(json.dumps(result(rev=rev)))
        out = Q.run(c, rp, {**os.environ, "PYTHONPATH": str(ROOT / "src")}, d / "work")
        self.assertTrue(out["assembled"], out)
        bad = [x for x in out["cases"] if not x["ok"]]
        self.assertEqual(bad, [])
        self.assertGreaterEqual(len(out["cases"]), 16)
        self.assertTrue(out["all_ok"])
        rb = out["rollback"]
        self.assertEqual([x for x in rb["cases"] if not x["ok"]], [])
        self.assertGreaterEqual(len(rb["cases"]), 16)
        self.assertTrue(rb["all_ok"])

    def test_fixture_without_lock_is_reported_not_silently_ok(self):
        d = tmpdir(self)
        (d / "c").mkdir()
        subprocess.run(["git", "init", "-q"], cwd=d / "c", check=True)
        subprocess.run(["git", "-c", "user.name=q", "-c", "user.email=q@x.invalid", "commit", "-q",
                        "--allow-empty", "-m", "c"], cwd=d / "c", check=True, capture_output=True)  # fmt: skip
        rp = d / "r.json"
        rp.write_text(json.dumps(result()))
        self.assertIn("skipped", Q.run(d / "c", rp, dict(os.environ), d / "w"))


if __name__ == "__main__":
    unittest.main()
