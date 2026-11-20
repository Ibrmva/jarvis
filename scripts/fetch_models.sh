#!/usr/bin/env bash
# Fetch the whisper.cpp GGML model that speech recognition shells out to.
#
# The model is ~57 MB and does not belong in git. Run this once after cloning:
#
#     ./scripts/fetch_models.sh
#
# Override the model or pin with environment variables:
#     WHISPER_MODEL=ggml-small-q5_1.bin ./scripts/fetch_models.sh
#     WHISPER_SHA256=<hash> ./scripts/fetch_models.sh
#
# Note: ggml-base-q5_1.bin is the model the project was developed against. The
# pinned hash below was measured from the copy that shipped inside the original
# repository; re-derive it yourself from a trusted download if you want a hard
# provenance guarantee.

set -euo pipefail

MODEL="${WHISPER_MODEL:-ggml-base-q5_1.bin}"
EXPECTED_SHA256="${WHISPER_SHA256:-422f1ae452ade6f30a004d7e5c6a43195e4433bc370bf23fac9cc591f01a8898}"
BASE_URL="${WHISPER_BASE_URL:-https://huggingface.co/ggerganov/whisper.cpp/resolve/main}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST_DIR="$REPO_ROOT/models/whisper"
DEST="$DEST_DIR/$MODEL"

mkdir -p "$DEST_DIR"

if [[ -f "$DEST" ]]; then
  echo "already present: $DEST"
else
  echo "downloading $MODEL ..."
  curl -fL --progress-bar "$BASE_URL/$MODEL" -o "$DEST.part"
  mv "$DEST.part" "$DEST"
fi

if command -v sha256sum >/dev/null 2>&1; then
  ACTUAL="$(sha256sum "$DEST" | awk '{print $1}')"
elif command -v shasum >/dev/null 2>&1; then
  ACTUAL="$(shasum -a 256 "$DEST" | awk '{print $1}')"
else
  echo "warning: no sha256 tool found, skipping checksum" >&2
  exit 0
fi

if [[ "$MODEL" == "ggml-base-q5_1.bin" && "$ACTUAL" != "$EXPECTED_SHA256" ]]; then
  echo "checksum mismatch for $MODEL" >&2
  echo "  expected $EXPECTED_SHA256" >&2
  echo "  actual   $ACTUAL" >&2
  echo "delete $DEST and retry, or set WHISPER_SHA256 to the hash you trust" >&2
  exit 1
fi

echo "ok: $DEST"
echo "sha256 $ACTUAL"
