"""Python lint aspect owned by the platform: ruff (lint and format) and ty over py_* targets.

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

    ty_out = ctx.actions.declare_file(target.label.name + ".dp_ty")
    imports = " ".join(target[PyInfo].imports.to_list())
    ctx.actions.run_shell(
        inputs = depset([ctx.file._ty_config], transitive = [target[PyInfo].transitive_sources]),
        outputs = [ty_out],
        tools = [ctx.executable._ty],
        command = "r=--extra-search-path=.; for i in {i}; do if [ -d external/$i ]; then r=\"$r --extra-search-path=external/$i\"; fi; done; {t} check --no-progress --config-file {c} $r {p} && touch {o}".format(
            i = imports,
            t = ctx.executable._ty.path,
            c = ctx.file._ty_config.path,
            p = paths,
            o = ty_out.path,
        ),
        mnemonic = "DpTy",
        progress_message = "ty %s" % target.label,
    )
    return [OutputGroupInfo(dp_py_checks = depset([ruff_out, ty_out]))]

dp_py_lint_aspect = aspect(
    implementation = _impl,
    attr_aspects = ["deps"],
    attrs = {
        "_ruff": attr.label(default = "//dev-platform:ruff", executable = True, cfg = "exec"),
        "_ruff_config": attr.label(default = "//dev-platform:ruff.toml", allow_single_file = True),
        "_ty": attr.label(default = "//dev-platform:ty", executable = True, cfg = "exec"),
        "_ty_config": attr.label(default = "//dev-platform:ty.toml", allow_single_file = True),
    },
)
