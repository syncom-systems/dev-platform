"""Python rules owned by the platform: pytest-based tests with Bazel coverage."""

load("@rules_python//python:defs.bzl", "py_test")

def _dp_executable_impl(ctx):
    out = ctx.actions.declare_file(ctx.label.name)
    ctx.actions.symlink(output = out, target_file = ctx.file.src, is_executable = True)
    return [DefaultInfo(executable = out, files = depset([out]), runfiles = ctx.runfiles(files = [ctx.file.src]))]

dp_executable = rule(
    implementation = _dp_executable_impl,
    attrs = {"src": attr.label(allow_single_file = True, mandatory = True)},
    executable = True,
)

def dp_py_test(name, srcs, deps = [], args = [], data = [], **kwargs):
    """A py_test that runs `srcs` with the platform's pinned pytest (and LCOV coverage under `bazel coverage`)."""
    py_test(
        name = name,
        srcs = srcs + ["//dev-platform:pytest_main.py"],
        main = "//dev-platform:pytest_main.py",
        args = ["$(rootpath %s)" % s for s in srcs] + args,
        data = data + ["//dev-platform:coveragerc"],
        deps = deps + ["@dp_pytools//pytest", "@dp_pytools//pytest_cov"],
        **kwargs
    )
