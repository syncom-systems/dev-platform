# 0.1.0-rc.3: FAILED attempt (retained as history; never promoted)

- Tag `v0.1.0-rc.3` (annotated), source revision `e8d11e9` (merge of PR #33). Workflow run 38066977458.
- Outcome: the `build` job failed at "Build environment must be certifiable"; `verify` and `publish` were
  skipped. **No archive, attestation, or GitHub release exists for this tag.** The tag is protected by
  the `v*` ruleset and stays where it is; the version is burned. Do not use or accept it.
- Cause (found by reproducing the step in a throwaway PR job, closed): the pinned ruff binary links
  `libgcc_s.so.1` on linux-x86_64, which was not in the declared `system_libs`, so closure verification
  correctly refused `closure-verified` and the environment was `diagnostic`. The release gate
  (`--require-certifiable`) did its job.
- Contributing defect (also fixed): the `environment` CI job piped `toolchain verify` into `tee` without
  `pipefail`, so the same failure had been masked in PR CI. This was a gap in the development
  verification, not in the release gate.
- Diagnostics were lost because the step redirected stdout to a file; the step now prints the record on
  failure.
- Next: `0.1.0-rc.4` from a corrected commit. rc.3 is not retroactively fixed or re-tagged.
