#!/usr/bin/env bash
# Sets up OpenVoice V2 (voice cloning) and SadTalker (talking-avatar generation)
# inside the GitHub Actions workspace. Both are research repos, not pip packages,
# so this clones them and wires up CPU-only torch (no GPU on GitHub-hosted runners).
#
# Layout after this runs:
#   third_party/OpenVoice/          <- cloned repo + checkpoints_v2/
#   third_party/SadTalker/          <- cloned repo + checkpoints/ + gfpgan/
set -euo pipefail

ROOT_DIR="$(pwd)"
THIRD_PARTY="$ROOT_DIR/third_party"
mkdir -p "$THIRD_PARTY"
cd "$THIRD_PARTY"

echo "== CPU-only torch (shared by both tools) =="
pip install --quiet torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu

echo "== 'av' (PyAV) — force the precompiled wheel, which bundles its own FFmpeg, to avoid a Cython/system-FFmpeg version mismatch when building from source =="
pip install --quiet --only-binary=:all: "av"

# ---------------------------------------------------------------------------
# OpenVoice V2
# ---------------------------------------------------------------------------
if [ ! -d "OpenVoice" ]; then
  echo "== Cloning OpenVoice =="
  git clone --depth 1 https://github.com/myshell-ai/OpenVoice.git
fi
cd OpenVoice
pip install --quiet -e .
pip install --quiet git+https://github.com/myshell-ai/MeloTTS.git
python -m unidic download

if [ ! -d "checkpoints_v2" ]; then
  echo "== Downloading OpenVoice V2 checkpoints =="
  curl -sL -o checkpoints_v2.zip \
    https://myshell-public-repo-hosting.s3.amazonaws.com/openvoice/checkpoints_v2_0417.zip
  unzip -q checkpoints_v2.zip
  rm checkpoints_v2.zip
fi
cd "$THIRD_PARTY"

# ---------------------------------------------------------------------------
# SadTalker
# ---------------------------------------------------------------------------
if [ ! -d "SadTalker" ]; then
  echo "== Cloning SadTalker =="
  git clone --depth 1 https://github.com/OpenTalker/SadTalker.git
fi
cd SadTalker
# Install requirements.txt but skip the CUDA-pinned torch lines the repo ships with —
# we already installed CPU wheels above and don't want them overwritten.
grep -viE '^torch(vision|audio)?==' requirements.txt > requirements.cpu.txt
pip install --quiet -r requirements.cpu.txt
pip install --quiet dlib-bin

if [ ! -f "checkpoints/SadTalker_V0.0.2_256.safetensors" ]; then
  echo "== Downloading SadTalker checkpoints =="
  bash scripts/download_models.sh
fi
cd "$ROOT_DIR"

echo "== Avatar model setup complete =="
