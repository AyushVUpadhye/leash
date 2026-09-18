#!/usr/bin/env bash
# Build the Lambda dependency layer for Linux x86_64 / python3.11 on ANY host OS.
# Uses uv's cross-platform resolver so environment markers (e.g. pywin32 on
# sys_platform == 'win32') are evaluated for the TARGET platform, not this machine.
# Output: .build/layer/python/  (the layout Lambda layers expect).
set -euo pipefail
cd "$(dirname "$0")/.."
OUT=".build/layer/python"
echo "[build-deps] resolving layer/requirements.txt for x86_64-manylinux2014 / cp311 -> $OUT"
python -m pip show uv >/dev/null 2>&1 || python -m pip install --quiet uv
rm -rf .build/layer && mkdir -p "$OUT"
uv pip install \
  --python-platform x86_64-manylinux2014 \
  --python-version 3.11 \
  --only-binary :all: \
  --target "$OUT" \
  -r layer/requirements.txt
# strip things Lambda never needs, to keep the zip small
find "$OUT" -type d -name "__pycache__" -prune -exec rm -rf {} + 2>/dev/null || true
rm -rf "$OUT/bin"
echo "[build-deps] done: $(du -sh "$OUT" | cut -f1), pywin32 present: $(ls "$OUT" | grep -ci win32 || true)"
