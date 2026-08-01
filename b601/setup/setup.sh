#!/usr/bin/env bash
# Bootstrap the B601 track. Written to run on the ROBOT PC (Ubuntu, RTX 5090,
# B601 arm + CAN adapter + RealSense), which is NOT the machine this repo was
# scaffolded on. Nothing here has been executed against that hardware yet —
# treat first run as part of the plan's Day-2 bring-up, and fix this script
# rather than working around it.
#
# Stages are idempotent. `env` is a PREREQUISITE of the other two, because both
# run under the repository interpreter rather than an ambient python:
#   env       create .venv and install pinned deps           (run this first)
#   verify    run the unpowered test suite                   (requires env)
#   hardware  probe GPU/CAN/RealSense — REPORTS ONLY,        (requires env)
#             never enables or moves anything
# A missing venv produces an actionable error, not a bare exit 127.
#
# Deliberately absent: any stage that powers or moves the robot. Motion
# happens through the tested primitives, never through a setup script.
set -euo pipefail

REPO="${B601_REPO:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
BOOTSTRAP_PY="${B601_BOOTSTRAP_PY:-python3}"
VENV="$REPO/.venv"

stage="${1:-all}"
case "$stage" in env|verify|hardware|all) ;; *)
    echo "usage: setup.sh [env|verify|hardware|all]" >&2; exit 64 ;;
esac

do_env() {
    echo "=== env ==="
    [ -d "$VENV" ] || "$BOOTSTRAP_PY" -m venv "$VENV"
    "$VENV/bin/pip" install --quiet --upgrade pip
    "$VENV/bin/pip" install --quiet -r "$REPO/b601/setup/requirements.txt"
    echo "venv: $VENV"
    "$VENV/bin/python" -c "import sys; print('python', sys.version.split()[0])"
}

require_env() {
    [ -x "$VENV/bin/python" ] || {
        echo "FATAL: no interpreter at $VENV/bin/python" >&2
        echo "       run 'bash b601/setup/setup.sh env' first" >&2
        exit 1
    }
}

do_verify() {
    require_env
    echo "=== verify (unpowered) ==="
    # PYTHONPATH= guards against a polluted parent environment (ROS on some
    # boxes injects packages that break pytest collection).
    PYTHONPATH= "$VENV/bin/python" -m pytest "$REPO/b601/tests/" -q
}

do_hardware() {
    require_env
    echo "=== hardware probe (report only, nothing is enabled) ==="
    echo "--- GPU ---"
    nvidia-smi --query-gpu=index,name,memory.total --format=csv,noheader 2>/dev/null \
        || echo "  no nvidia-smi"
    echo "--- CAN interfaces ---"
    ip -br link show type can 2>/dev/null || echo "  none reported"
    echo "--- RealSense cameras ---"
    if command -v rs-enumerate-devices >/dev/null 2>&1; then
        rs-enumerate-devices -s 2>/dev/null || true
    else
        "$VENV/bin/python" - <<'PY' 2>/dev/null || echo "  pyrealsense2 not installed"
import pyrealsense2 as rs
for d in rs.context().devices:
    print("  ", d.get_info(rs.camera_info.name),
          "serial", d.get_info(rs.camera_info.serial_number))
PY
    fi
    echo
    echo "NEXT: record serials into b601/setup/cameras.json, calibrate (Day 3),"
    echo "then 'bash b601/setup/pin_check.sh --record' to freeze the pins."
}

case "$stage" in
    env)      do_env ;;
    verify)   do_verify ;;
    hardware) do_hardware ;;
    all)      do_env; do_verify; do_hardware ;;
esac
echo "setup: $stage done"
