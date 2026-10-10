import tomllib
import unittest

from dev_platform.config import parse
from dev_platform.errors import ConfigError
from tests.helpers import SHA, cfg_text


def load(text):
    return parse(tomllib.loads(text))


def problems(text):
    with unittest.TestCase().assertRaises(ConfigError) as cm:
        load(text)
    return "\n".join(cm.exception.problems)


FAST = ("a", '["pre-merge"]', "change", '["src/**"]')


class ConfigTest(unittest.TestCase):
    def test_valid_minimal(self):
        cfg = load(cfg_text([FAST]))
        self.assertEqual(cfg.checks[0].id, "a")
        self.assertEqual(cfg.platform.sha256, SHA)

    def test_wrong_schema_version(self):
        self.assertIn(
            "schema_version", problems(cfg_text([FAST]).replace("schema_version = 1", "schema_version = 2"))
        )

    def test_unknown_keys_are_errors(self):
        self.assertIn("unknown top-level key", problems("bogus = 1\n" + cfg_text([FAST])))
        self.assertIn("unknown key", problems(cfg_text([FAST]).replace('name = "t"', 'name = "t"\ntypo = 1')))

    def test_pin_must_be_exact_and_hashed(self):
        bad = cfg_text([FAST]).replace('version = "0.1.0"', 'version = "^0.1"')
        self.assertIn("ranges are not allowed", problems(bad))
        bad = cfg_text([FAST]).replace(SHA, "abc")
        self.assertIn("platform.sha256", problems(bad))

    def test_self_hosted_excludes_pin(self):
        text = cfg_text(
            [FAST], platform="schema_version = 1\n[platform]\nself_hosted = true\n[project]\nname = 't'\n"
        )
        self.assertTrue(load(text).platform.self_hosted)
        with_pin = text.replace("self_hosted = true", 'self_hosted = true\nversion = "1.0.0"')
        self.assertIn("excludes", problems(with_pin))

    def test_mandatory_check_cannot_skip_pre_merge(self):
        # cost is irrelevant; a mandatory check must be admissible at pre-merge
        text = cfg_text([("slow", '["full"]', "change", '["src/**"]')])
        self.assertIn("must include stage 'pre-merge'", problems(text))
        text = cfg_text([("slow", '["full"]', "always", "[]")])
        self.assertIn("must include stage 'pre-merge'", problems(text))

    def test_periodic_must_run_in_full(self):
        self.assertIn("periodic", problems(cfg_text([("p", '["pre-merge"]', "periodic", "[]")])))
        load(cfg_text([("p", '["full"]', "periodic", "[]")]))

    def test_change_check_needs_inputs(self):
        self.assertIn("must declare inputs", problems(cfg_text([("a", '["pre-merge"]', "change", "[]")])))

    def test_duplicate_ids_rejected(self):
        self.assertIn("duplicate", problems(cfg_text([FAST, FAST])))

    def test_bazel_only_forbids_cargo(self):
        extra = ""
        text = cfg_text([], extra=extra).replace('name = "t"', 'name = "t"\nbazel_only = true') + (
            '\n[[check]]\nid = "c"\nadapter = "cargo"\nstages = ["pre-merge"]\ninputs = ["**"]\n'
        )
        self.assertIn("cargo adapter is prohibited", problems(text))
        text = text.replace('adapter = "cargo"', 'adapter = "exec"\nargv = ["/usr/bin/cargo", "test"]')
        self.assertIn("invoking cargo directly", problems(text))

    def test_runner_requirements_are_logical(self):
        extra = '\n[runner.x]\nos = "linux"\nlabels = ["self-hosted"]\n'
        self.assertIn("physical runner names", problems(cfg_text([FAST], extra=extra)))

    def test_unknown_runner_reference(self):
        text = cfg_text([FAST]) + 'runner = "nope"\n'
        self.assertIn("not defined under [runner", problems(text))

    def test_adapter_argument_requirements(self):
        text = cfg_text([]) + '[[check]]\nid="b"\nadapter="bazel"\nstages=["pre-merge"]\ninputs=["**"]\n'
        self.assertIn("requires targets", problems(text))

    def test_no_checks(self):
        self.assertIn("at least one", problems(cfg_text([])))


if __name__ == "__main__":
    unittest.main()
