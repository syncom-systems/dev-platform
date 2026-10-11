import unittest

from dev_platform import config, toolchain
from dev_platform.errors import ConfigError

BASE = """
schema_version = 1
[platform]
version = "1.0.0"
sha256 = "%(sha)s"
profile = "p"
[project]
name = "x"
[[check]]
id = "a"
adapter = "exec"
argv = ["true"]
stages = ["pre-merge", "full"]
obligation = "change"
inputs = ["**"]
%(extra)s
"""


def parse(extra):
    import tomllib

    return config.parse(tomllib.loads(BASE % {"sha": "0" * 64, "extra": extra}))


ENV = {
    "profile": "p",
    "platform": "linux-x86_64",
    "conformant": True,
    "assurance": "certifiable",
    "identity_digest": "a" * 64,
    "weak_tools": [],
    "tools": [],
    "scope": {"hermetic": False, "limitations": ["base"]},
}


def probe_for(code, text):
    return lambda argv: (code, text)


class Declare(unittest.TestCase):
    def test_valid(self):
        cfg = parse(
            '[[host]]\nname = "tmux"\nargv = ["tmux", "-V"]\npattern = "tmux (\\\\S+)"\nversion = "3"\n'
        )
        self.assertEqual((cfg.host_tools[0].name, cfg.host_tools[0].version), ("tmux", "3"))

    def test_invalid(self):
        for bad in (
            '[[host]]\nname = "Tmux"\nargv = ["t"]\npattern = "(x)"\n',
            '[[host]]\nname = "t"\npattern = "(x)"\n',
            '[[host]]\nname = "t"\nargv = ["t"]\npattern = "no group"\n',
            '[[host]]\nname = "t"\nargv = ["t"]\npattern = "("\n',
            '[[host]]\nname = "t"\nargv = ["t"]\npattern = "(x)"\nextra = 1\n',
            '[[host]]\nname = "t"\nargv = ["t"]\npattern = "(x)"\n[[host]]\nname = "t"\nargv = ["t"]\npattern = "(x)"\n',
        ):
            with self.assertRaises(ConfigError, msg=bad):
                parse(bad)


class Observe(unittest.TestCase):
    def reqs(self, code, text, version=None):
        h = config.HostTool("tmux", ("tmux", "-V"), r"tmux (\S+)", version)
        return toolchain.host_requirements([h], probe_for(code, text))

    def test_ok_mismatch_unavailable(self):
        self.assertEqual(self.reqs(0, "tmux 3.5a")[0]["status"], "ok")
        self.assertEqual(self.reqs(0, "tmux 3.5a", "3")[0]["status"], "ok")
        self.assertEqual(self.reqs(0, "tmux 3.5a", "3.5a")[0]["status"], "ok")
        self.assertEqual(self.reqs(0, "tmux 2.9", "3")[0]["status"], "mismatch")
        self.assertEqual(self.reqs(127, "")[0]["status"], "unavailable")
        self.assertEqual(self.reqs(0, "garbage")[0]["status"], "unavailable")

    def test_gates_conformance_but_never_raises_assurance(self):
        ok = toolchain.with_host_requirements(ENV, self.reqs(0, "tmux 3.5"))
        self.assertTrue(ok["conformant"])
        self.assertEqual(ok["assurance"], "certifiable")
        self.assertNotEqual(ok["identity_digest"], ENV["identity_digest"])
        self.assertTrue(any("tmux" in x and "not by content" in x for x in ok["scope"]["limitations"]))
        self.assertIs(ok["scope"]["hermetic"], False)
        bad = toolchain.with_host_requirements(ENV, self.reqs(127, ""))
        self.assertEqual((bad["conformant"], bad["assurance"]), (False, "diagnostic"))

    def test_identity_changes_with_observed_version(self):
        a = toolchain.with_host_requirements(ENV, self.reqs(0, "tmux 3.4"))
        b = toolchain.with_host_requirements(ENV, self.reqs(0, "tmux 3.5"))
        self.assertNotEqual(a["identity_digest"], b["identity_digest"])

    def test_no_declarations_leaves_the_record_untouched(self):
        self.assertIs(toolchain.with_host_requirements(ENV, []), ENV)
        self.assertNotIn("host_requirements", ENV)

    def test_does_not_mutate_its_input(self):
        toolchain.with_host_requirements(ENV, self.reqs(0, "tmux 3.5"))
        self.assertEqual(ENV["scope"]["limitations"], ["base"])


if __name__ == "__main__":
    unittest.main()
