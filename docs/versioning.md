# [DRAFT] Versoning recommendations
## SemVer-inspired policy while we're pre-1.0:
```
0.MINOR.PATCH
```

| Change | Version |
|---|---|
| Bug fix, packaging fix, small correction without a new capability | `0.1.0 → 0.1.1` |
| New user-visible capability or meaningful behavior change | `0.1.x → 0.2.0` |
| Breaking change while still pre-1.0 | usually `0.2.x → 0.3.0` |
| Internal refactor only, not released independently | no bump |
| Docs/tests only | normally no bump unless you're explicitly releasing them |
| Preparing a release containing multiple changes | bump once for the release |

## Rules
```
pyproject.toml
    = authoritative application version

Git tag
    = v<pyproject version>

GitHub Release
    = same version

Installer filenames
    = generated from that version

distribution-metadata.json
    = same application version
```