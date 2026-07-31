#!/usr/bin/env bash
# Bootstrap the B601 track. Written to run on the ROBOT PC (Ubuntu, RTX 5090,
# B601 arm + CAN adapter + RealSense), which is NOT the machine this repo was
# scaffolded on. Nothing here has been executed against that hardware yet —
# treat first run as part of the plan's Day-2 bring-up, and fix this script
# rather than working around it.
#
# Stages are independent and idempotent:
#   env       create .venv and install pinned deps
#   verify    run the unpowered test suite (no arm, no cameras needed)
#   hardware  probe for the arm, CAN adapter and cameras — REPORTS ONLY,
#             never enables or moves anything
#
# Deliberately absent: any stage that powers or moves the robot. Motion
# happens through the tested primitives, never through a setup script.
set -euo pipefail

REPO="${B601_REPO:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
PY="${B601_PY:-python3}"
VENV="$REPO/.venv"

stage="${1:-all}"
case "$stage" in env|verify|hardware|all) ;; *)
    echo "usage: setup.sh [env|verify|hardware|all]" >&2; exit 64 ;;
esac

do_env() {
    echo "=== env ==="
    [ -d "$VENV" ] || "$PY" -m venv "$VENV"
    "$VENV/bin/pip" install --quiet --upgrade pip
    "$VENV/bin/pip" install --quiet -r "$REPO/b601/setup/requirements.txt"
    echo "venv: $VENV"
    "$VENV/bin/python" -c "import sys; print('python', sys.version.split()[0])"
}

do_verify() {
    echo "=== verify (unpowered) ==="
    # PYTHONPATH= guards against a polluted parent environment (ROS on some
    # boxes injects packages that break pytest collection).
    PYTHONPATH= "$VENV/bin/python" -m pytest "$REPO/b601/tests/" -q
}

do_hardware() {
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
