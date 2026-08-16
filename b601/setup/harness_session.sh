#!/usr/bin/env bash
# Harness trial session (shakedown and Day-18): the HARNESS drives the arm —
# staging moves, frozen-policy invocations, verification, retries. Same gate
# stack as the evaluation; a harness run on drifted cameras or wrong pins
# measures the wrong thing.
#
# SAFETY: autonomous powered motion. Operator within reach of the e-stop for
# EVERY trial. Trials never auto-start — each waits for ENTER. Every command
# (staged moves AND policy) passes the per-tick rate limiter and the
# divergence guard; a guard trip ends the trial with no further motion.
set -euo pipefail

REPO="${B601_REPO:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
CONDA_PY="${B601_PY:-/home/demo/miniforge3/envs/lerobot/bin/python}"
BACKUP="${B601_BACKUP:-/mnt/nvme3/b601}"

TRIALS="${1:-}"
[ -n "$TRIALS" ] || { echo "usage: harness_session.sh <num_trials> [--dry-run|extra args]" >&2; exit 64; }

fail() { echo "GATE FAILED: $*" >&2; exit 1; }
run_py() { PYTHONNOUSERSITE=1 PYTHONPATH="$REPO" "$CONDA_PY" "$@"; }

echo "=== 1/5  experiment identity (pin_check) ==="
B601_PY="$CONDA_PY" bash "$REPO/b601/setup/pin_check.sh" \
    || fail "pins do not verify — an unattributable run is not evidence"

echo "=== 2/5  fresh D405 session + manifest onto the cameras ==="
run_py -m b601.cameras.reset || fail "D405 reset"
run_py -m b601.cameras.capture || fail "camera settings"

echo "=== 3/5  preflight (drift gate) ==="
run_py -m b601.cameras.preflight || fail "preflight"

echo "=== 4/5  fresh D405 session for the harness's own cameras ==="
run_py -m b601.cameras.reset || fail "D405 reset (second)"
run_py -m b601.cameras.capture || fail "camera settings (second)"

echo "=== 5/5  backup destination ==="
touch "$BACKUP/.write_test" 2>/dev/null || fail "backup not writable: $BACKUP"
rm -f "$BACKUP/.write_test"

echo
echo "=== HARNESS SESSION: E-STOP IN REACH. Training lighting ONLY. ==="
echo "  Each trial: place the block at the declared target, park the arm,"
echo "  hands clear, THEN press ENTER. Score by eye AND by the recorded"
echo "  outcome; declare any redo BEFORE running it."
echo

run_py -m b601.planner.run_harness --trials "$TRIALS" "${@:2}"

echo
echo "=== backup ==="
rsync -a "$REPO/outputs/harness_trials/" "$BACKUP/harness_trials/"
echo "harness telemetry backed up"
