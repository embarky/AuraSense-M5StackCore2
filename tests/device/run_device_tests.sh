#!/usr/bin/env bash
# Run the firmware tests on the MicroPython unix port.
#   Requires: micropython (apt install micropython) and mpy-cross (pip install mpy-cross)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

echo "== Compile every firmware file with the MicroPython compiler"
for f in "$ROOT"/device/*.py "$ROOT"/device/pages/*.py; do
  mpy-cross -o "$WORK/check.mpy" "$f"
done
echo "ok"

echo "== Run firmware tests on MicroPython $(micropython -c 'import sys; print(sys.implementation.version)')"
cp -r "$ROOT"/device/. "$WORK"/
cp "$ROOT"/tests/device/stubs/*.py "$WORK"/
cp "$ROOT"/tests/device/test_device.py "$WORK"/
cp "$WORK"/config.example.py "$WORK"/config.py
cd "$WORK" && micropython test_device.py
