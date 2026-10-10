# Immutable-release publishing probe (2026-10-10)

Purpose: observe the real repository configuration (immutable releases enabled; ruleset
`release-tags-immutable` 24840008 on `refs/tags/v*`, rules `deletion` + `update`, no bypass actors),
including failure cases, without touching any platform release or its tag. Probe artifacts are not
platform releases and carry no trust claim.

Probe A: tag `immutability-probe-1` (outside the ruleset pattern) at 27e75cd, released with
`gh release create <tag> a.txt --verify-tag --prerelease`, exactly as `release.yml` publishes.

| Action on the published release | Observed |
|---|---|
| `immutable` flag on the new release | `true` |
| Upload another asset | HTTP 422 "Cannot upload assets to an immutable release" |
| Overwrite an asset (`--clobber`) | HTTP 422, same message |
| Delete an asset | rejected, "Cannot delete asset from an immutable release" |
| Move the tag (force PATCH) | HTTP 422 |
| Delete the tag while the release exists | HTTP 422 |
| `gh release verify`, `gh release verify-asset` | succeed; asset digest matches |
| Edit release notes | allowed (notes are not part of the immutable payload) |
| Delete the release | **allowed** |
| Re-create a release for the same tag name | HTTP 422 "tag_name was used by an immutable release" |
| Delete the tag after the release was deleted | **allowed** (tag removed; name stays reserved for releases) |

Conclusion: immutable releases protect the tag and assets only while the release exists, and an
administrator can delete the release and then the tag. The tag ruleset closes that gap for `v*` tags.

Probe B: tag `vprobe-1` (matches `refs/tags/v*`, does not match the release workflow trigger) at 27e75cd.
Force-moving it: HTTP 422 "Cannot update this protected ref". Deleting it: HTTP 422 "Cannot delete this
tag". The tag remains, by design, as evidence that the ruleset is enforced; it is not a release.

Residual risk: a repository administrator can edit or disable the ruleset or the immutable-releases
setting. That is outside what this repository can enforce on itself; verification therefore never
relies on GitHub state alone (digests and Sigstore attestations are checked independently), and a
change to those settings is an owner-level event.
