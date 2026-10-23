"""Rust rules owned by the platform: a library with its unit tests and documentation checks."""

load("@rules_rust//rust:defs.bzl", "rust_doc", "rust_doc_test", "rust_library", "rust_test")

EDITION = "@@EDITION@@"

def dp_rust_library(name, srcs, deps = [], **kwargs):
    """rust_library plus `<name>_test` (unit tests), `<name>_doc` (rustdoc) and `<name>_doctest`."""
    rust_library(name = name, srcs = srcs, deps = deps, edition = EDITION, **kwargs)
    rust_test(name = name + "_test", crate = ":" + name, edition = EDITION)
    rust_doc(name = name + "_doc", crate = ":" + name)
    rust_doc_test(name = name + "_doctest", crate = ":" + name)
