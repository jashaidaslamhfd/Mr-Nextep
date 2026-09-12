# Audit follow-up: what this branch does not fix

Three audit items are deliberately left out of this branch because they need either a
credential action only the repo owner can take, or a history rewrite that must be
coordinated with anyone holding a clone.

## 1. Rotate the leaked Pixabay API key — OWNER ACTION REQUIRED

`config/.env` was committed at `9df92ab` with a real `PIXABAY_API_KEY`, then deleted at
`2e7402f`. Deleting a file does not remove it from git history: on a public repository
that key is still retrievable by anyone, permanently, and should be assumed scraped.

No code change can fix this. Required steps:

1. Revoke and reissue the key in the Pixabay account.
2. Store the new value as the `PIXABAY_API_KEY` GitHub Actions secret. The workflow
   already reads `secrets.PIXABAY_API_KEY`, so nothing else needs to change.
3. Enable GitHub secret scanning and push protection on the repository.

## 2. Purge git history — needs coordination

`.git` is ~63 MB for ~2,000 lines of code. Two separate reasons to rewrite:

- the leaked `config/.env` blob (see above)
- ~50 MB of deleted media still in history: `assets/voice_reference.wav` (11.7 MB),
  `assets/music/cosmic_mystery.wav` and `brain_tension.wav` (10.6 MB each), plus five
  quarantined MP3s

Both are fixed by one `git-filter-repo` pass followed by a force-push. This rewrites
every commit SHA, so it must happen when no unmerged work is outstanding, and every
existing clone must be re-cloned afterwards. Rotating the key (step 1) is what actually
makes the leak harmless; the purge only stops it being trivially discoverable.

Note: `assets/` is referenced nowhere in the current code, so the background-music
feature is either dropped or dead weight — worth an explicit decision before the purge.

## 3. Move pipeline state off git — larger change, deferred

`_git_persist()` commits `data/*.json` back to `main` on every run. Of 1,741 commits,
the overwhelming majority are `chore: reserve generated video state` /
`chore: finalize generated video state` pairs, which makes history unusable for review —
precisely how a patch blob reached `src/main.py` unnoticed.

`.gitignore` encodes the contradiction directly: `data/*` followed by `!data/*.json`.

The fix is to move the six state files to a GitHub Actions cache, a release asset, or a
small hosted KV store. That changes the pipeline's persistence and recovery model, so it
belongs in its own branch with its own testing rather than riding along with correctness
fixes. Until then, the newly added CI workflow (which runs on push and pull request)
covers the review gap that the commit noise created.
