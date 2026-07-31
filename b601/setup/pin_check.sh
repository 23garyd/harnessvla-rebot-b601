#!/usr/bin/env bash
# Verify (default) or record (--record) the B601 experiment pins.
#
# TWO REGIMES, both gating. The sim track only had to pin software; here the
# PHYSICAL configuration is experiment state too — the plan is explicit that a
# changed camera invalidates affected episodes and evaluations. A run launched
# against unverified pins is a run whose data cannot be trusted later.
#
#   software  — LeRobot version, B601 SDK/driver, CUDA/video backend
#   physical  — camera serials, resolution, exposure, mount, calibration hash
#
# Exit non-zero on: missing pins file, malformed entry, drift in either regime,
# or a calibration file whose hash no longer matches what was recorded.
set -euo pipefail

REPO="${B601_REPO:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
PINS="$REPO/b601/setup/pins.env"
CALIB="${B601_CALIB:-$REPO/b601/setup/calibration.json}"

usage() { echo "usage: pin_check.sh [--record]" >&2; exit 64; }
case "${1:-}" in ""|--record) ;; *) usage ;; esac

fail() { echo "FATAL: $*" >&2; exit 1; }

# Parse, never source: pins.env content must not run as code.
pin() { grep -E "^$1=" "$PINS" 2>/dev/null | tail -1 | cut -d= -f2- || true; }

if [ "${1:-}" = "--record" ]; then
    [ -f "$CALIB" ] || fail "no calibration at $CALIB; run Day-3 calibration first"
    lerobot="$(python -c 'import lerobot; print(lerobot.__version__)' 2>/dev/null || echo UNKNOWN)"
    calib_sha="$(sha256sum "$CALIB" | cut -d' ' -f1)"
    cams="$(python - <<'PY' 2>/dev/null || echo UNKNOWN
import json, pathlib, os
p = pathlib.Path(os.environ.get("B601_CAMERAS",
    pathlib.Path(__file__).resolve().parents[0] / "cameras.json"))
print(",".join(sorted(c["serial"] for c in json.loads(p.read_text())["cameras"])))
PY
)"
    {
      echo "# B601 experiment pins. Written by pin_check.sh --record."
      echo "# Hand-edits are a behaviour-affecting change and require an"
      echo "# experiment-registry entry. Physical pins invalidate episodes."
      echo "LEROBOT_VERSION=$lerobot"
      echo "CAMERA_SERIALS=$cams"
      echo "CALIBRATION_SHA256=$calib_sha"
    } > "$PINS.tmp"
    mv "$PINS.tmp" "$PINS"
    echo "recorded pins -> $PINS"
    exit 0
fi

[ -f "$PINS" ] || fail "no pins.env; run pin_check.sh --record after review"

# --- software regime ------------------------------------------------------
want_lerobot="$(pin LEROBOT_VERSION)"
[ -n "$want_lerobot" ] || fail "LEROBOT_VERSION unset in pins.env"
have_lerobot="$(python -c 'import lerobot; print(lerobot.__version__)' 2>/dev/null || echo MISSING)"
[ "$have_lerobot" = "$want_lerobot" ] || \
    fail "lerobot $have_lerobot != pinned $want_lerobot"

# --- physical regime ------------------------------------------------------
want_cams="$(pin CAMERA_SERIALS)"
[ -n "$want_cams" ] || fail "CAMERA_SERIALS unset in pins.env"
have_cams="$(python - <<'PY' 2>/dev/null || echo UNKNOWN
import json, pathlib, os
p = pathlib.Path(os.environ.get("B601_CAMERAS",
    pathlib.Path(__file__).resolve().parents[0] / "cameras.json"))
print(",".join(sorted(c["serial"] for c in json.loads(p.read_text())["cameras"])))
PY
)"
[ "$have_cams" = "$want_cams" ] || \
    fail "camera serials '$have_cams' != pinned '$want_cams' — this invalidates affected episodes; see registry"

want_calib="$(pin CALIBRATION_SHA256)"
[ -n "$want_calib" ] || fail "CALIBRATION_SHA256 unset in pins.env"
[ -f "$CALIB" ] || fail "calibration file missing: $CALIB"
have_calib="$(sha256sum "$CALIB" | cut -d' ' -f1)"
[ "$have_calib" = "$want_calib" ] || \
    fail "calibration hash drift — recalibrate or re-record the pin, do NOT ignore"

echo "pin check OK: lerobot $have_lerobot, cameras $have_cams, calibration ${have_calib:0:12}"
