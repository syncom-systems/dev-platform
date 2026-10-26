"""Repository isolation, completed (ADR 0027): no destination chosen by a caller, flag, variable or default can
put platform output into a consuming project's working tree or Git metadata; `toolchain materialize` writes
nothing into a project; the infrastructure store has one location calculation.

Every refusal is proven by comparing the whole project tree (bytes, modes, timestamps, links, `.git`) before and
after, not by `git status`.
"""

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

from dev_platform import infra_store, locations, pathguard
from dev_platform.errors import ConfigError
from tests.helpers import ROOT, tmpdir
from tests.repo_snapshot import changed, snapshot

TOML = (
    'schema_version = 1\n[platform]\nversion = "0.17.0"\nsha256 = "' + "a" * 64 + '"\nprofile = "py"\n'
    'source_revision = "' + "b" * 40 + '"\narchive_sha256 = "' + "c" * 64 + '"\n'
    '[platform.verifier_pins]\nverify_release = "' + "1" * 64 + '"\ntrust_policy = "' + "2" * 64 + '"\n'
    'install_release = "' + "3" * 64 + '"\n[project]\nname = "consumer"\n'
    '[[check]]\nid = "t"\nadapter = "exec"\nargv = ["true"]\nstages = ["pre-merge", "full"]\nobligation = "always"\n'
)


def git_init(d: Path) -> None:
    subprocess.run(["git", "init", "-q", str(d)], check=True)


def make_project(test, toml: str = TOML) -> tuple[Path, Path]:
    """(base, project): a Git repository holding dev-platform.toml; base is a scratch directory outside it."""
    base = tmpdir(test).resolve()
    proj = base / "proj"
    (proj / "sub").mkdir(parents=True)
    git_init(proj)
    (proj / "dev-platform.toml").write_text(toml)
    (proj / "README.md").write_text("hello\n")
    (proj / "sub" / "keep.txt").write_text("keep\n")
    return base, proj


def cli(args, cwd, env_extra=None):
    env = {k: v for k, v in os.environ.items() if k not in ("CI", "GITHUB_ACTIONS", "PYTHONPATH")}
    env.update({"PYTHONPATH": str(ROOT / "src"), **(env_extra or {})})
    return subprocess.run(
        [sys.executable, "-m", "dev_platform", *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        timeout=60,
    )


class Guard(unittest.TestCase):
    def setUp(self):
        self.base, self.proj = make_project(self)

    def refused(self, path, project=None):
        return pathguard.refusal(path, "x", project, cwd=self.base)

    def test_inside_the_tree_and_the_git_metadata_is_refused(self):
        for p in (
            self.proj,
            self.proj / "new.json",
            self.proj / "sub" / "deeper" / "x",
            self.proj / ".git",
            self.proj / ".git" / "hooks" / "pre-commit",
            self.proj / "sub" / ".." / "x",
        ):
            self.assertIn("repository isolation", self.refused(p, self.proj) or "", p)

    def test_outside_is_allowed_including_a_sibling_with_the_same_prefix(self):
        for p in (
            self.base / "out.json",
            self.base / "proj2" / "x",
            self.base / "proj-x",
            Path("/nonexistent/a"),
        ):
            self.assertIsNone(self.refused(p, self.proj), p)

    def test_a_symlink_into_the_project_is_judged_by_its_target(self):
        link = self.base / "link"
        link.symlink_to(self.proj / "sub")
        self.assertIsNotNone(self.refused(link / "x", self.proj))
        dangling = self.base / "dangling"
        dangling.symlink_to(self.proj / "not-yet" / "x")  # a link whose target does not exist yet
        self.assertIsNotNone(self.refused(dangling, self.proj))
        chain = self.base / "chain"
        chain.symlink_to(link)
        self.assertIsNotNone(self.refused(chain / "x", self.proj))
        inside_to_outside = self.proj / "out"
        inside_to_outside.symlink_to(self.base)
        self.assertIsNone(self.refused(inside_to_outside / "result.json", self.proj))  # lands outside

    def test_the_project_is_found_from_the_working_directory_too(self):
        self.assertIsNotNone(pathguard.refusal(self.proj / "sub" / "x", "x", None, cwd=self.proj / "sub"))
        self.assertIsNone(pathguard.refusal(self.base / "x", "x", None, cwd=self.proj / "sub"))

    def test_a_linked_worktree_protects_its_metadata_and_the_main_one(self):
        wt = self.base / "wt"
        subprocess.run(["git", "-C", str(self.proj), "add", "-A"], check=True)
        subprocess.run(
            ["git", "-C", str(self.proj), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "i"],
            check=True,
        )
        subprocess.run(["git", "-C", str(self.proj), "worktree", "add", "-q", str(wt)], check=True)
        self.assertIsNotNone(pathguard.refusal(wt / "x", "x", wt, cwd=self.base))
        gitdir = Path(os.path.realpath((wt / ".git").read_text().split(":", 1)[1].strip()))
        self.assertIsNotNone(pathguard.refusal(gitdir / "x", "x", wt, cwd=self.base))
        self.assertIsNotNone(pathguard.refusal(self.proj / ".git" / "x", "x", wt, cwd=self.base))

    def test_the_platform_repository_itself_is_not_protected(self):
        _, own = make_project(
            self,
            TOML.replace(
                TOML[TOML.index("[platform]") : TOML.index("[project]")],
                '[platform]\nself_hosted = true\nprofile = "dev-platform"\n',
            ),
        )
        self.assertIsNone(pathguard.refusal(own / "dist" / "x", "x", own, cwd=own))

    def test_an_invalid_pin_file_still_protects(self):
        base, proj = make_project(self, "this is not toml [")
        self.assertIsNotNone(pathguard.refusal(proj / "x", "x", proj, cwd=base))

    def test_guard_raises_a_config_error_and_passes_none_through(self):
        with self.assertRaises(ConfigError):
            pathguard.guard(self.proj / "x", "--out", self.proj, cwd=self.base)
        self.assertIsNone(pathguard.guard(None, "--out", self.proj))


SINKS = [  # (what, argv given the destination)
    ("check --result", lambda p: ["check", "--result", p]),
    ("toolchain provision --dest", lambda p: ["toolchain", "provision", "--profile", "py", "--dest", p]),
    ("toolchain provision default --dest", None),
    ("toolchain prepare --dest", lambda p: ["toolchain", "prepare", "--dest", p]),
    ("toolchain prove-bazel-rust --out", lambda p: ["toolchain", "prove-bazel-rust", "--out", p]),
    ("release build --out", lambda p: ["release", "build", "--version", "0.0.1", "--out", p]),
    ("release pack --out", lambda p: ["release", "pack", "sub", "--out", p]),
    (
        "release install --store",
        lambda p: ["release", "install", "a.tgz", "--archive-sha256", "0" * 64, "--store", p],
    ),
    (
        "provenance assemble --out",
        lambda p: [
            "provenance",
            "assemble",
            "--result",
            "r.json",
            "--name",
            "n",
            "--app-version",
            "1",
            "--source-uri",
            "u",
            "--out",
            p,
        ],
    ),
    ("evidence put --store", lambda p: ["evidence", "put", "--store", p, "README.md"]),
    ("evidence bundle --out", lambda p: ["evidence", "bundle", "--out", p, "--release", "r.json"]),
    (
        "dependency-snapshot --out",
        lambda p: [
            "dependency-snapshot",
            "--platform-version",
            "0.17.0",
            "--sha",
            "a" * 40,
            "--ref",
            "refs/heads/m",
            "--job-id",
            "1",
            "--scanned",
            "2026-10-26T00:00:00Z",
            "--out",
            p,
        ],
    ),
    ("workflow --output", lambda p: ["workflow", "--output", p]),
    ("infra init --root", lambda p: ["infra", "init", "--owner", "o", "--root", p]),
    ("infra release build --root", lambda p: ["infra", "release", "build", "2026.01.1", "--root", p]),
    (
        "infra resolve --evidence-out",
        lambda p: ["infra", "resolve", "--root", "/nonexistent", "--evidence-out", p],
    ),
    ("infra store list --store", lambda p: ["infra", "store", "list", "--store", p]),
    ("setup --store", lambda p: ["setup", "--store", p]),
    ("setup --toolchains", lambda p: ["setup", "--toolchains", p]),
    ("setup --cache", lambda p: ["setup", "--cache", p]),
    ("setup --home", lambda p: ["setup", "--home", p]),
    ("install --store", lambda p: ["install", "--version", "0.17.0", "--profile", "py", "--store", p]),
    (
        "install --infra-store",
        lambda p: ["install", "--version", "0.17.0", "--profile", "py", "--infra-store", p],
    ),
    ("install --home", lambda p: ["install", "--version", "0.17.0", "--profile", "py", "--home", p]),
]


class Sinks(unittest.TestCase):
    """Every caller-chosen destination, spelled four ways, is refused with the tree untouched."""

    def setUp(self):
        self.base, self.proj = make_project(self)
        self.outside_home = self.base / "home"
        (self.base / "link").symlink_to(self.proj / "sub")

    def spellings(self):
        return {
            "absolute": (str(self.proj / "sub" / "out"), self.proj),
            "relative": ("sub/out", self.proj),
            "relative-from-a-subdirectory": ("../out-up", self.proj / "sub"),
            "dotdot": (str(self.proj / "sub" / ".." / "out2"), self.proj),
            "through-a-symlink": (str(self.base / "link" / "out"), self.proj),
            "git-metadata": (str(self.proj / ".git" / "out"), self.proj),
        }

    def assertRefused(self, what, argv, cwd, env_extra=None):
        before = snapshot(self.proj)
        r = cli(argv, cwd, {"DEV_PLATFORM_HOME": str(self.outside_home), **(env_extra or {})})
        self.assertEqual(r.returncode, 2, f"{what}: {r.stdout}{r.stderr}")
        self.assertIn("repository isolation", r.stderr, what)
        self.assertEqual(changed(before, snapshot(self.proj)), {}, what)

    def test_every_output_flag_and_location_flag_is_guarded(self):
        for what, build in SINKS:
            if build is None:
                continue
            for name, (dest, cwd) in self.spellings().items():
                with self.subTest(sink=what, spelling=name):
                    self.assertRefused(what, build(dest), cwd)

    def test_the_default_provision_destination_is_refused_inside_a_project(self):
        self.assertRefused("toolchain provision", ["toolchain", "provision", "--profile", "py"], self.proj)

    def test_environment_overrides_are_guarded(self):
        cases = [
            ("DEV_PLATFORM_HOME", "."),
            ("DEV_PLATFORM_HOME", "sub/home"),
            ("DEV_PLATFORM_STORE", str(self.proj / "versions")),
            ("DEV_PLATFORM_STORE", "versions"),
            ("DEV_PLATFORM_TOOLCHAINS", str(self.proj / "tc")),
            ("DEV_PLATFORM_CACHE", ".cache"),
            ("XDG_DATA_HOME", str(self.proj / "data")),
        ]
        for var, value in cases:
            for argv in (
                ["setup", "--dry-run"],
                ["install", "--version", "0.17.0", "--profile", "py", "--dry-run"],
            ):
                with self.subTest(var=var, value=value, cmd=argv[0]):
                    # one override at a time: another data root variable would mask it
                    env = {"DEV_PLATFORM_HOME": "", "XDG_DATA_HOME": "", var: value}
                    if var not in ("DEV_PLATFORM_HOME", "XDG_DATA_HOME"):
                        env["DEV_PLATFORM_HOME"] = str(self.outside_home)
                    before = snapshot(self.proj)
                    r = cli(argv, self.proj, env)
                    self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
                    self.assertIn("repository isolation", r.stderr)
                    self.assertEqual(changed(before, snapshot(self.proj)), {})

    def test_infra_store_overrides_cannot_reach_the_project(self):
        for env in ({"DEV_PLATFORM_HOME": "."}, {"DEV_PLATFORM_HOME": str(self.proj)}):
            before = snapshot(self.proj)
            r = cli(["infra", "store", "list"], self.proj, env)
            self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
            self.assertEqual(changed(before, snapshot(self.proj)), {})

    def test_outside_destinations_are_not_refused_by_the_guard(self):
        out = self.base / "out"
        r = cli(["infra", "init", "--owner", "o", "--root", str(out)], self.proj)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue((out / "dev-platform.infra-config.json").exists() or any(out.iterdir()))
        # the same flags pointing outside are not the guard's business (they may fail for other reasons)
        for what, build in SINKS:
            if build is None or what.startswith(
                ("install", "setup", "toolchain provision", "toolchain prepare")
            ):
                continue  # these need network or a release; their locations are covered by the refusal tests
            r = cli(
                build(str(self.base / "elsewhere" / "x")),
                self.proj,
                {"DEV_PLATFORM_HOME": str(self.outside_home)},
            )
            self.assertNotIn("repository isolation", r.stderr, what)

    def test_the_platform_repository_keeps_its_maintainer_operations(self):
        own_toml = 'schema_version = 1\n[platform]\nself_hosted = true\nprofile = "dev-platform"\n[project]\nname = "own"\n'
        _base, own = make_project(self, own_toml)
        r = cli(["infra", "init", "--owner", "o", "--root", str(own / "cfg")], own)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue((own / "cfg").is_dir())


class Materialize(unittest.TestCase):
    """`toolchain materialize` no longer writes Bazel files or entry lines into a project; inspection stays."""

    def setUp(self):
        self.base, self.proj = make_project(self)
        self.profile = "python-ty-bazel-9.3"
        self.manifest = str(ROOT / "toolchains" / "manifest.json")

    def run_materialize(self, *extra):
        return cli(
            ["toolchain", "materialize", "--manifest", self.manifest, "--profile", self.profile, *extra],
            self.proj,
            {"DEV_PLATFORM_HOME": str(self.base / "home")},
        )

    def test_every_writing_mode_is_refused_and_the_project_is_unchanged(self):
        for extra in ((), ("--add-hooks",), ("--create-hooks",), ("--add-hooks", "--create-hooks")):
            before = snapshot(self.proj)
            r = self.run_materialize(*extra)
            self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
            self.assertIn("repository isolation", r.stderr)
            self.assertIn("--check and --dry-run", r.stderr)
            self.assertEqual(changed(before, snapshot(self.proj)), {}, extra)

    def test_inspection_writes_nothing(self):
        for extra in (("--check",), ("--dry-run",), ("--dry-run", "--add-hooks"), ("--check", "--json")):
            before = snapshot(self.proj)
            r = self.run_materialize(*extra)
            self.assertIn(r.returncode, (0, 1), r.stdout + r.stderr)
            self.assertNotIn("repository isolation", r.stderr)
            self.assertEqual(changed(before, snapshot(self.proj)), {}, extra)

    def test_a_directory_that_is_not_a_project_can_still_be_rendered_into_for_maintainers(self):
        out = self.base / "fixture"
        out.mkdir()
        before = snapshot(self.proj)
        r = cli(
            [
                "toolchain",
                "materialize",
                "--manifest",
                self.manifest,
                "--profile",
                self.profile,
                "--project",
                str(out),
                "--create-hooks",
            ],
            self.base,
        )
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue((out / "dev-platform" / "generated.json").exists())
        self.assertEqual(changed(before, snapshot(self.proj)), {})


class StoreLocation(unittest.TestCase):
    """One calculation of the infrastructure store, for `install` and every `infra` command."""

    def test_platform_store_overrides_never_move_the_infra_store(self):
        home = tmpdir(self).resolve() / "h"
        base = {"DEV_PLATFORM_HOME": str(home)}
        want = (home / "infra", "DEV_PLATFORM_HOME")
        self.assertEqual(infra_store.location(base), want)
        for extra in (
            {"DEV_PLATFORM_STORE": "/elsewhere/versions"},
            {"DEV_PLATFORM_TOOLCHAINS": "/t"},
            {"DEV_PLATFORM_CACHE": "/c"},
        ):
            self.assertEqual(infra_store.location({**base, **extra}), want, extra)
        self.assertEqual(infra_store.location({}, home=home)[0], home / "infra")
        self.assertEqual(infra_store.location(base, store=Path("/x/infra")), (Path("/x/infra"), "--store"))

    def test_the_default_is_the_data_root_the_other_locations_use(self):
        for env in ({"DEV_PLATFORM_HOME": "/h"}, {"XDG_DATA_HOME": "/d"}, {}):
            loc = locations.locate(env)
            self.assertEqual(infra_store.location(env)[0], loc.store.parent / "infra", env)

    def test_install_and_infra_commands_agree_through_the_cli(self):
        base, proj = make_project(self)
        home = base / "home"
        env = {"DEV_PLATFORM_HOME": str(home), "DEV_PLATFORM_STORE": str(base / "vers")}
        r = cli(["infra", "store", "list"], proj, env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(json.loads(r.stdout)["store"], str(home / "infra"))

    def test_a_store_inside_the_project_is_refused_by_the_calculation_itself(self):
        _base, proj = make_project(self)
        for kw in (dict(store=proj / "infra"), dict(store=Path("infra")), dict(home=proj)):
            with self.subTest(kw=kw):
                cwd = os.getcwd()
                os.chdir(proj)
                try:
                    with self.assertRaises(ConfigError):
                        infra_store.location({}, project=proj, **kw)
                finally:
                    os.chdir(cwd)


if __name__ == "__main__":
    unittest.main()
