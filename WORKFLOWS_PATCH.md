# workflows.patch — apply this locally

The Arena GitHub App is not granted the `workflows` OAuth scope, so it is
**refused by GitHub** when a push touches `.github/workflows/`:

```
! [remote rejected] refusing to allow a GitHub App to create or update
  workflow `.github/workflows/ci.yml` without `workflows` permission
```

Everything else in the review landed normally. The six workflow edits are
therefore shipped as `workflows.patch` in the repo root.

## Apply it

```bash
git checkout arena/019fa26d-skillor
git apply workflows.patch          # or: git apply --3way workflows.patch
git add .github/workflows
git commit -m "ci: upload dated audit reports as artifacts; unify test runner"
git push                            # your own credentials have the scope
git rm workflows.patch WORKFLOWS_PATCH.md && git commit -m "chore: drop applied patch"
```

Verify before committing:

```bash
python -m compileall -q src scripts tests
python -m unittest discover -s tests -v      # expect: 23 tests, OK (4 skipped)
```

## What the patch changes

**1. `fb_audit.yml`, `fb_diag.yml`, `seo_diag_us.yml`, `video_audit_us.yml`**

Each ended with a `git add data/<report>_*.json && git commit && git push`
step. Since the scripts now write to the git-ignored `data/reports/`, that
step would find nothing and silently do nothing. It is replaced with:

```yaml
- name: Upload <name> report as artifact
  uses: actions/upload-artifact@v4
  with:
    name: <name>
    path: data/reports/
    if-no-files-found: warn
    retention-days: 90
```

The report is still downloadable from the run page for 90 days — it just no
longer grows the repository forever.

These four jobs are read-only now, so `permissions: contents: write` was
narrowed to `contents: read`.

**2. `fb_tuneup.yml`**

Split into two steps. The dated report goes to artifacts, but
`data/fb_thumbs_done.json` and `data/fb_welcome_done.json` are **still
committed** — `fb_page_tuneup.py` reads them back on the next run to avoid
redoing work, so they are durable state, not a report. This job keeps
`contents: write`.

**3. `ci.yml`**

- Ran `pytest` while `main.yml` ran `unittest discover` — two gates that could
  disagree about what passes. Both use `unittest discover` now, and the
  redundant `pip install pytest` is gone.
- `tests/` added to the compile gate (previously only `src scripts`), which is
  what actually caught the broken import below.
- Added a `pull_request` trigger. Previously CI only ran on push to `main`,
  i.e. a broken branch was caught *after* it was already merged.

## Note on the test suite

Before this work, `python -m unittest discover -s tests` reported
`Ran 16 tests ... FAILED (errors=1)` — `tests/test_core.py` failed to import
because `trend_fetcher` needs `requests`. With dependencies installed the full
suite is discovered and green:

```
Ran 23 tests in 0.015s
OK (skipped=4)
```

No test logic was modified; the 7 previously-hidden tests are the contents of
`test_core.py` that the import error was masking.
