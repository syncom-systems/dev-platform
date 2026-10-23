"""Python lint aspect owned by the platform: ruff (lint and format) and mypy over py_* targets.

Run with `bazel build --config=dp-lint //...` (see bazel.bazelrc); output group `dp_py_checks`.
"""

load("@rules_python//python:defs.bzl", "PyInfo")

def _impl(target, ctx):
    if PyInfo not in target or target.label.package == "dev-platform":
        return []
    srcs = [
        f
        for f in getattr(ctx.rule.files, "srcs", [])
        if f.extension == "py" and not f.short_path.startswith("dev-platform/")
    ]
    if not srcs:
        return []
    paths = " ".join([f.path for f in srcs])

    ruff_out = ctx.actions.declare_file(target.label.name + ".dp_ruff")
    ctx.actions.run_shell(
        inputs = srcs + [ctx.file._ruff_config],
        outputs = [ruff_out],
        tools = [ctx.executable._ruff],
        command = "{r} check --no-cache --config {c} {p} && {r} format --check --no-cache --config {c} {p} && touch {o}".format(
            r = ctx.executable._ruff.path,
            c = ctx.file._ruff_config.path,
            p = paths,
            o = ruff_out.path,
        ),
        mnemonic = "DpRuff",
        progress_message = "ruff %s" % target.label,
    )

    mypy_out = ctx.actions.declare_file(target.label.name + ".dp_mypy")
    roots = ["."] + ["external/" + i for i in target[PyInfo].imports.to_list()]
    ctx.actions.run_shell(
        inputs = depset([ctx.file._mypy_config], transitive = [target[PyInfo].transitive_sources]),
        outputs = [mypy_out],
        tools = [ctx.executable._mypy],
        command = "MYPYPATH={mp} {m} --config-file {c} --cache-dir=/dev/null --explicit-package-bases {p} && touch {o}".format(
            mp = ":".join(roots),
            m = ctx.executable._mypy.path,
            c = ctx.file._mypy_config.path,
            p = paths,
            o = mypy_out.path,
        ),
        mnemonic = "DpMypy",
        progress_message = "mypy %s" % target.label,
    )
    return [OutputGroupInfo(dp_py_checks = depset([ruff_out, mypy_out]))]

dp_py_lint_aspect = aspect(
    implementation = _impl,
    attr_aspects = ["deps"],
    attrs = {
        "_ruff": attr.label(default = "//dev-platform:ruff", executable = True, cfg = "exec"),
        "_ruff_config": attr.label(default = "//dev-platform:ruff.toml", allow_single_file = True),
        "_mypy": attr.label(default = "//dev-platform:mypy", executable = True, cfg = "exec"),
        "_mypy_config": attr.label(default = "//dev-platform:mypy.ini", allow_single_file = True),
    },
)
