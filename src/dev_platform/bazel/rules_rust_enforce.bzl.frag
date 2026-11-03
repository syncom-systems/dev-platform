    # dev-platform (ADR 0028): the Rust toolchain is the one this verified rules_rust declares in its own
    # MODULE.bazel. A root `rust.toolchain` is accepted only when every platform-owned attribute equals the
    # verified declaration (its `edition`, a project-owned language default, may differ); any other root
    # `rust.toolchain`, and any root `rust.repository_set`, fails here instead of selecting another compiler.
    _dp_owned = [
        "aliases",
        "allocator_library",
        "dev_components",
        "extra_exec_rustc_flags",
        "extra_exec_rustc_flags_triples",
        "extra_rustc_flags",
        "extra_rustc_flags_triples",
        "extra_target_triples",
        "global_allocator_library",
        "opt_level",
        "rust_analyzer_version",
        "rustfmt_toolchain_triples",
        "rustfmt_version",
        "sha256s",
        "strip_level",
        "target_settings",
        "urls",
        "versions",
    ]
    root_edition = None
    if root != rules_rust:
        if root.tags.repository_set:
            fail("dev-platform: rust.repository_set in the root module is not allowed; the Rust toolchain is supplied by Dev Platform @@RELEASE@@ (ADR 0028)")
        dp = rules_rust.tags.toolchain[0]
        for t in root.tags.toolchain:
            for a in _dp_owned:
                if getattr(t, a, None) != getattr(dp, a, None):
                    fail("dev-platform: rust.toolchain(%s = %r) in the root module differs from the verified toolchain (%r); the Rust toolchain is supplied by Dev Platform @@RELEASE@@ (ADR 0028): remove it (a declaration equal to the verified one, with any `edition`, is accepted; per-target `edition` stays the project's)" %(a, getattr(t, a, None), getattr(dp, a, None)))
            root_edition = t.edition
    toolchains = rules_rust.tags.toolchain
