# Mr-Nextep Repository Audit

## Executive conclusion

The repository is currently healthy after the settings-precedence fix from the previous pass. The latest GitHub Actions CI run passed, and the second audit found two additional reliability issues that have now been remediated and covered by tests. The remaining items are lower-priority operational improvements rather than confirmed blockers.

## Findings and remediation

| Priority | Area | Finding | Status |
|---|---|---|---|
| High | External media downloads | A provider could omit `Content-Length`, allowing the streamed download to exceed the configured 45 MB cap before `ffmpeg` processed it. | Fixed. Downloads are now bounded while streaming, and oversized candidates are rejected so fallback sources can continue. |
| Medium | Instagram workflow | `publish_instagram.yml` supplied `INSTAGRAM_PROCESSING_WAIT_SECONDS`, but the standalone publisher used a hard-coded ten-second polling delay. | Fixed. The script now honors the configured interval and reports missing required environment variables clearly. |
| Medium | State persistence | Production runs commit generated JSON state back to `main`. Concurrent runs could still create a push race if they are started outside the production workflow's concurrency group. | Mitigated for scheduled/manual production runs by the existing concurrency group. A future improvement would be to move mutable state to an external store or use a dedicated state branch. |
| Medium | Third-party API maintenance | The standalone Instagram script, shared Meta module, and legacy metadata repair utility previously used different Graph API versions. | Fixed. All Meta integrations now use the shared `META_GRAPH_API_VERSION` setting, defaulting consistently to `v21.0`. |
| Low | Operational observability | `scripts/preflight.py` prints Python dictionary syntax rather than JSON and only checks local binaries/configuration. | Open improvement. Emit structured JSON and add explicit, non-secret checks for required production credentials and provider reachability. |
| Low | Input validation | The rescheduling scripts passed `VIDEO_ID`, comma-separated IDs, and `PUBLISH_AT` directly to the YouTube API. | Fixed. IDs and ISO-8601 UTC timestamps are validated before credentials or API calls are used. |
| Low | Testability | `scripts/publish_instagram.py` executed its full workflow at import time, which made unit testing and local reuse difficult. | Improved. Execution now lives in `main()` under an `if __name__ == '__main__'` guard, with URL validation and injectable polling parameters. |

## Validation performed

The following checks passed after remediation:

- Python byte-compilation for `src`, `scripts`, and `tests`.
- Ruff lint for all project Python files.
- The complete test suite: **95 tests passed**.
- Basic workflow structure checks for every GitHub Actions YAML file.
- The GitHub Actions CI run for commit `58b33d0` passed before this audit's new changes.

## Recommended next steps

The next useful hardening step is to add mocked HTTP tests for Instagram container creation, processing failure, timeout behavior, and successful publication. A later operational improvement would be moving mutable generated state out of Git and into a dedicated state store or state branch.
