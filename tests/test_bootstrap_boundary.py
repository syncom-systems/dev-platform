"""The launcher never interprets what it has not run: its path (resolve, projectsetup, bootstrap) neither
validates a release record nor a toolchain manifest. That is the release's job (docs/distribution.md)."""

import ast
import unittest

from tests.helpers import ROOT

SRC = ROOT / "src" / "dev_platform"
VALIDATORS = {
    ("releases", "load"),
    ("release", "load"),
    ("toolchain", "validate"),
    ("releases", "synthesize_for_checkout"),
}


def calls(path, allowed_in=()):
    """(module, attribute, enclosing function) of every `module.attr(...)` call."""
    tree = ast.parse(path.read_text())
    found = []

    def walk(node, fn):
        for child in ast.iter_child_nodes(node):
            name = child.name if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) else fn
            if (
                isinstance(child, ast.Call)
                and isinstance(child.func, ast.Attribute)
                and isinstance(child.func.value, ast.Name)
            ):
                found.append((child.func.value.id, child.func.attr, fn))
            walk(child, name)

    walk(tree, None)
    return found


class Boundary(unittest.TestCase):
    def test_the_launcher_resolves_without_validating_a_release(self):
        offenders = [
            c for c in calls(SRC / "resolve.py") if c[:2] in VALIDATORS and c[2] not in ("_load_release",)
        ]
        # the self/override branches read the running checkout, not a release a launcher is about to run
        self.assertEqual([c for c in offenders if c[:2] != ("releases", "synthesize_for_checkout")], [])

    def test_the_release_record_is_validated_only_by_the_release_itself(self):
        loads = [c for c in calls(SRC / "resolve.py") if c[:2] == ("releases", "load")]
        self.assertEqual(loads, [("releases", "load", "_load_release")])

    def test_setup_and_the_contract_never_validate_a_manifest(self):
        for name in ("projectsetup.py", "bootstrap.py"):
            self.assertEqual([c for c in calls(SRC / name) if c[:2] in VALIDATORS], [], name)
        imports = (SRC / "projectsetup.py").read_text()
        self.assertNotIn("from dev_platform import toolchain", imports)
        self.assertNotIn("from dev_platform.toolchain import", imports)
