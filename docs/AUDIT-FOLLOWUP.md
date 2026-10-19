# Audit follow-up: owner actions still required

Some findings need credential actions only the repository owner can take, or a history rewrite that must be coordinated with anyone holding a clone. This branch redacts the current `data/video_history.json` and removes generated/biometric files from the current tree, but prior Git commits still contain old blobs until history is rewritten.

## 1. Revoke the exposed Meta access token — OWNER ACTION REQUIRED

`data/video_history.json` contained repeated Meta Graph API error strings with an `access_token` query parameter. The current remediation branch redacts these values and adds error redaction to the Meta clients. That does not revoke the token or remove older Git blobs.

Required steps:

1. Revoke/rotate the affected Meta access token immediately.
2. Store the replacement only in GitHub Actions Secrets.
3. Verify the replacement works, then search repository history and workflow logs for the old value without pasting it into issues or chat.

## 2. Rotate the leaked Pixabay API key — OWNER ACTION REQUIRED

`config/.env` was committed at `9df92ab` with a real `PIXABAY_API_KEY`, then deleted at
`2e7402f`. Deleting a file does not remove it from git history: on a public repository
that key is still retrievable by anyone, permanently, and should be assumed scraped.

No code change can fix this. Required steps:

1. Revoke and reissue the key in the Pixabay account.
2. Store the new value as the `PIXABAY_API_KEY` GitHub Actions secret. The workflow
   already reads `secrets.PIXABAY_API_KEY`, so nothing else needs to change.
3. Enable GitHub secret scanning and push protection on the repository.

## 3. Purge git history — needs coordination

`.git` is ~63 MB for ~2,000 lines of code. Two separate reasons to rewrite:

- the leaked `config/.env` blob (see above)
- the Meta access token recorded in old `data/video_history.json` commits
- biometric assets and generated logs/media removed from the current tree
- ~50 MB of deleted media still in history: `assets/voice_reference.wav` (11.7 MB),
  `assets/music/cosmic_mystery.wav` and `brain_tension.wav` (10.6 MB each), plus five
  quarantined MP3s

Both are fixed by one `git-filter-repo` pass followed by a force-push. This rewrites
every commit SHA, so it must happen when no unmerged work is outstanding, and every
existing clone must be re-cloned afterwards. Rotating the key (step 1) is what actually
makes the leak harmless; the purge only stops it being trivially discoverable.

Note: `assets/` is referenced nowhere in the current code, so the background-music
feature is either dropped or dead weight — worth an explicit decision before the purge.

## 4. Move pipeline state off git — larger change, deferred

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


## Public biometric assets

The current remediation branch removes the face image and voice sample from the repository tree and changes the local avatar test to require private files supplied through `AVATAR_FACE_PATH` and `AVATAR_VOICE_SAMPLE_PATH`. The temporary public workflow that downloaded models and pushed test output has been removed. Do not re-add face/voice samples or generated setup logs to this public repository. Old commits still need the coordinated history purge above.
