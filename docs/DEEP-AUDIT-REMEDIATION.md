# Deep-audit remediation status

This branch implements code-level safeguards for two high-risk audit findings.

## Implemented here

- The pipeline now preserves the uploader's actual status. A dry run remains `dry_run`; it cannot be mislabeled as `uploaded`. A production result is only considered uploaded when the uploader reports success and returns a YouTube video ID.
- The manual "make public" workflow requires an explicit confirmation checkbox and explicit video IDs.
- Video IDs are validated and de-duplicated before any API mutation.
- The make-public script exits non-zero if any selected video is missing, inaccessible, or fails to transition. CI can now detect partial failure.
- Regression tests cover the status contract and ID validation.

## Required owner actions that code cannot perform

1. **Rotate the previously exposed Pixabay key immediately.** Revoke it at Pixabay and store a replacement only in GitHub Actions Secrets. Assume the old key is compromised even if it currently appears inactive.
2. **Purge the secret and large deleted media from Git history in a coordinated maintenance window.** This changes commit IDs and requires force-pushing rewritten history; collaborators must re-clone. Do not run an uncoordinated history rewrite while other work is in flight.
3. **Enable GitHub secret scanning and push protection** if available for this account/repository.
4. Review GitHub Actions run logs and YouTube Studio after merging, first with a manual dry run and then a controlled publish.

## Still requiring a separately tested architectural change

Pipeline state is currently committed back to `main` by `src/main.py::_git_persist`. Moving state to a durable external store or dedicated state branch needs migration, concurrency and recovery tests; it is intentionally not mixed into this correctness/security patch.

The production workflow's immediate-public behavior is preserved because it is an existing product setting. If scheduled videos should be private until a review step, change `YT_PRIVACY_STATUS` / `YT_SCHEDULE_PUBLISH` in the production workflow as a deliberate policy decision.
