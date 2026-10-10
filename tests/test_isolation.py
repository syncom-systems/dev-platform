import os
import sys
import unittest
from pathlib import Path

from dev_platform import isolation
from dev_platform.adapters import Command
from dev_platform.engine import make_executor
from tests.helpers import tmpdir


class Scrub(unittest.TestCase):
    def test_drops_everything_not_allowed(self):
        base = {
            "AWS_SECRET_ACCESS_KEY": "zq9-secret-value",
            "GITHUB_TOKEN": "t",
            "LANG": "C",
            "HOME": "/home/me",
            "FOO": "1",
        }
        env, rep = isolation.scrub(base, path_dirs=["/opt/t"], scratch=tmpdir(self))
        self.assertEqual(set(env), {"LANG", "PATH", "TMPDIR", "HOME"})
        self.assertNotEqual(env["HOME"], "/home/me")
        self.assertEqual(env["PATH"], "/opt/t:/usr/bin:/bin")
        self.assertEqual(rep["inherited_dropped"], 4)
        self.assertNotIn("zq9-secret-value", str(rep))  # names, never values
        self.assertTrue(any("not isolated" in x for x in rep["limits"]))

    def test_keep_is_explicit(self):
        env, _ = isolation.scrub(
            {"HOME": "/h", "FOO": "1"}, path_dirs=[], scratch=tmpdir(self), keep=("HOME", "FOO")
        )
        self.assertEqual((env["HOME"], env["FOO"]), ("/h", "1"))

    def test_executor_sees_only_scrubbed(self):
        d = tmpdir(self)
        os.environ["DP_SECRET_PROBE"] = "x"
        self.addCleanup(os.environ.pop, "DP_SECRET_PROBE", None)
        env, _ = isolation.scrub(dict(os.environ), path_dirs=[], scratch=d / "s")
        out = d / "out"
        code = (
            "import os,sys;open(sys.argv[1],'w').write('DP_SECRET_PROBE' in os.environ and 'leak' or 'clean')"
        )
        for ex, want in ((make_executor(env), "clean"), (make_executor(), "leak")):
            ex(Command((sys.executable, "-c", code, str(out)), ()), d)
            self.assertEqual(Path(out).read_text(), want)


if __name__ == "__main__":
    unittest.main()
