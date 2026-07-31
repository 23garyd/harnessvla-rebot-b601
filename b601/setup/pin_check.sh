#!/usr/bin/env bash
# Verify (default) or record (--record) the B601 experiment pins.
#
# TWO REGIMES, both gating. The sim track only had to pin software; here the
# PHYSICAL configuration is experiment state too — the plan is explicit that a
# changed camera invalidates affected episodes and evaluations.
#
#   software  — LeRobot version (as seen by THIS repo's interpreter)
#   physical  — camera serials, calibration file hash
#
# INTERPRETER: probes run under the repository venv, never an ambient `python`.
# On a normal shell, bare `python` can easily be a conda base or system install
# carrying a different LeRobot, which would silently gate on the wrong
# environment. Resolution order: $B601_PY, then .venv/bin/python, then fail.
#
# NO SILENT FALLBACKS: a probe that cannot determine its value aborts. An
# earlier version degraded to `|| echo UNKNOWN`, which recorded UNKNOWN and
# then verified UNKNOWN == UNKNOWN — a gate that passes while checking nothing.
set -euo pipefail

REPO="${B601_REPO:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
PINS="${B601_PINS:-$REPO/b601/setup/pins.env}"
CALIB="${B601_CALIB:-$REPO/b601/setup/calibration.json}"
CAMERAS="${B601_CAMERAS:-$REPO/b601/setup/cameras.json}"

usage() { echo "usage: pin_check.sh [--record]" >&2; exit 64; }
case "${1:-}" in ""|--record) ;; *) usage ;; esac

fail() { echo "FATAL: $*" >&2; exit 1; }

# --- resolve the interpreter ---------------------------------------------
PY="${B601_PY:-$REPO/.venv/bin/python}"
[ -x "$PY" ] || fail "no repository interpreter at $PY — run 'bash b601/setup/setup.sh env' first, or set B601_PY"

probe() {
    # $1 = probe name, $2 = optional path. Aborts on probe failure.
    local out
    if ! out="$( cd "$REPO" && "$PY" -m b601.setup.probe "$@" 2>&1 )"; then
        fail "$out"
    fi
    printf '%s' "$out"
}

# Parse, never source: pins.env content must not run as code.
pin() { grep -E "^$1=" "$PINS" 2>/dev/null | tail -1 | cut -d= -f2- || true; }

# --- record ---------------------------------------------------------------
if [ "${1:-}" = "--record" ]; then
    lerobot="$(probe lerobot-version)"
    cams="$(probe camera-serials "$CAMERAS")"
    calib_sha="$(probe calibration-sha256 "$CALIB")"
    {
      echo "# B601 experiment pins. Written by pin_check.sh --record."
      echo "# Hand-edits are a behaviour-affecting change and require an"
      echo "# experiment-registry entry. Physical pins invalidate episodes."
      echo "# Recorded with interpreter: $PY"
      echo "LEROBOT_VERSION=$lerobot"
      echo "CAMERA_SERIALS=$cams"
      echo "CALIBRATION_SHA256=$calib_sha"
    } > "$PINS.tmp"
    mv "$PINS.tmp" "$PINS"
    echo "recorded pins -> $PINS"
    exit 0
fi

# --- verify ---------------------------------------------------------------
[ -f "$PINS" ] || fail "no pins.env; run pin_check.sh --record after review"

want_lerobot="$(pin LEROBOT_VERSION)"
want_cams="$(pin CAMERA_SERIALS)"
want_calib="$(pin CALIBRATION_SHA256)"
[ -n "$want_lerobot" ] || fail "LEROBOT_VERSION unset in pins.env"
[ -n "$want_cams" ]    || fail "CAMERA_SERIALS unset in pins.env"
[ -n "$want_calib" ]   || fail "CALIBRATION_SHA256 unset in pins.env"

have_lerobot="$(probe lerobot-version)"
[ "$have_lerobot" = "$want_lerobot" ] || \
    fail "lerobot $have_lerobot != pinned $want_lerobot (interpreter $PY)"

have_cams="$(probe camera-serials "$CAMERAS")"
[ "$have_cams" = "$want_cams" ] || \
    fail "camera serials '$have_cams' != pinned '$want_cams' — this invalidates affected episodes; see b601/registry/experiment_registry.md"

have_calib="$(probe calibration-sha256 "$CALIB")"
[ "$have_calib" = "$want_calib" ] || \
    fail "calibration hash drift — recalibrate or re-record the pin, do NOT ignore"

echo "pin check OK: lerobot $have_lerobot, cameras $have_cams, calibration ${have_calib:0:12} (interpreter $PY)"
