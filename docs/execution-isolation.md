# Execution isolation (scope and status)

Tool identity (closure digests) says which bytes run. It does not say what the process inherits or can reach.

`dev-platform check --isolate-env` runs check commands with a **scrubbed environment**: an empty start, an
allowlist (locale, TERM, TZ, proxy and CA variables), a PATH of the verified tools' directories plus `/usr/bin:/bin`,
and a private `HOME`/`TMPDIR`. `--isolate-keep NAME` opts a variable back in explicitly. The result records an
`execution` object: mode, variable *names* passed, count dropped (never values), the PATH, and the limits.

Not isolated, and stated in every result: filesystem, network, processes, kernel. This is not a sandbox and not
hermeticity. Default mode (`inherited`) is unchanged and says so in `execution`.

Status: qualified for the `python` profile only (`tools/qualify.py --isolate-env`, darwin-arm64 locally). The
Bazel and Cargo profiles are not claimed under scrubbed mode (Bazelisk and Cargo caches live under HOME; their
behaviour under a private HOME is untested). Making scrubbed mode mandatory for certification is a policy decision
and is not made here. Nothing in this changes v0.1.0, which predates it.
