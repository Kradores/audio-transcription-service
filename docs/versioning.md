# Versioning

## Pre-1.0 versioning policy

While the project is pre-1.0, versions use:

```text
0.MINOR.PATCH
```

| Change | Version |
|---|---|
| Bug fix, packaging fix, or small correction without a new capability | `0.1.0 → 0.1.1` |
| New user-visible capability or meaningful behavior change | `0.1.x → 0.2.0` |
| Breaking change while still pre-1.0 | normally increment MINOR |
| Internal refactor only, not released independently | no bump |
| Docs/tests only | normally no bump unless explicitly released |
| Release containing multiple changes | bump once for the release |

The project does not attempt to encode every individual change into the
version. The version identifies a released application state.

## Version source of truth

```text
pyproject.toml
    = authoritative application version

Git tag
    = v<pyproject version>

GitHub Release
    = same version

Installer filenames
    = generated from that version

distribution-metadata.json
    = generated from that version
```

Version values must not be duplicated manually when they can be derived from
`pyproject.toml`.

Build scripts, installer generation, and distribution metadata should consume
the authoritative project version.

## Release consistency

A release is valid only when these values agree:

```text
pyproject.toml project.version
        =
Git tag without the v prefix
        =
GitHub Release version
        =
packaged distribution application_version
        =
installer filename version
```

A Git tag alone is not considered a complete application release.

## Release workflow

1. Choose the release version.
2. Finalize the changelog for that version.
3. Update `pyproject.toml`.
4. Run the repository quality gate.
5. Build release artifacts after the version bump.
6. Verify generated distribution metadata and installer filenames.
7. Commit the release state.
8. Create tag `v<VERSION>` on that commit.
9. Push the commit and tag.
10. Publish the GitHub Release from that tag and attach the release artifacts.
11. Verify the published release and assets.

Release artifacts must be built from the exact commit referenced by the release
tag.