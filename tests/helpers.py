import shutil
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "fixtures"
SHA = "0" * 64

BASE = """
schema_version = 1
[platform]
version = "0.1.0"
sha256 = "%s"
[project]
name = "t"
"""

CHECK = """
[[check]]
id = "%s"
adapter = "exec"
argv = ["true"]
stages = %s
obligation = "%s"
inputs = %s
"""


def cfg_text(checks=(), extra="", platform=None):
    out = BASE % SHA if platform is None else platform
    out += extra
    for cid, stages, ob, inputs in checks:
        out += CHECK % (cid, stages, ob, inputs)
    return out


def tmpdir(test):
    d = Path(tempfile.mkdtemp())
    test.addCleanup(shutil.rmtree, d, ignore_errors=True)
    return d


def copy_fixture(test, name):
    d = tmpdir(test) / name
    shutil.copytree(FIXTURES / name, d)
    return d
