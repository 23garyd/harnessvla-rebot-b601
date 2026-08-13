#!/usr/bin/env bash
# Day-14 held-out evaluation: the POLICY drives the arm; the operator
# supervises with the e-stop and scores each trial. Same gates as recording —
# an evaluation on drifted cameras or wrong pins measures the wrong thing.
#
# SAFETY: this is autonomous powered motion. Operator within reach of the
# e-stop for EVERY trial; ESC aborts the session; each episode is capped at
# EVAL_TIME_S so a confused policy cannot run indefinitely.
set -euo pipefail

REPO="${B601_REPO:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
CONDA_PY="${B601_PY:-/home/demo/miniforge3/envs/lerobot/bin/python}"
CONDA_BIN="$(dirname "$CONDA_PY")"
BACKUP="${B601_BACKUP:-/mnt/nvme3/b601}"
POLICY="${B601_POLICY:-$REPO/artifacts/act_b601_v1_20260812/checkpoints/100000/pretrained_model}"
EVAL_TIME_S="${B601_EVAL_TIME_S:-40}"

TRIALS="${1:-}"
[ -n "$TRIALS" ] || { echo "usage: eval_session.sh <num_trials> [extra lerobot args]" >&2; exit 64; }

DATASET_ID="${B601_DATASET_ID:-eval_b601_v1}"
DATASET_ROOT="${B601_DATASET_ROOT:-$REPO/datasets/$DATASET_ID}"

fail() { echo "GATE FAILED: $*" >&2; exit 1; }
run_py() { PYTHONNOUSERSITE=1 PYTHONPATH="$REPO" "$CONDA_PY" "$@"; }

echo "=== 1/5  experiment identity (pin_check) ==="
B601_PY="$CONDA_PY" bash "$REPO/b601/setup/pin_check.sh" \
    || fail "pins do not verify — an unattributable evaluation is not evidence"

echo "=== 2/5  fresh D405 session + manifest onto the cameras ==="
run_py -m b601.cameras.reset || fail "D405 reset"
run_py -m b601.cameras.capture || fail "camera settings"

echo "=== 3/5  preflight ==="
run_py -m b601.cameras.preflight || fail "preflight"

echo "=== 4/5  fresh D405 session for the policy's own cameras ==="
run_py -m b601.cameras.reset || fail "D405 reset (second)"
run_py -m b601.cameras.capture || fail "camera settings (second)"

echo "=== 5/5  backup destination ==="
touch "$BACKUP/.write_test" 2>/dev/null || fail "backup not writable: $BACKUP"
rm -f "$BACKUP/.write_test"

RESUME_ARGS=()
if [ -d "$DATASET_ROOT" ] && [ -n "$(find "$DATASET_ROOT" -name '*.parquet' 2>/dev/null | head -1)" ]; then
    echo "  appending to existing evaluation dataset"
    RESUME_ARGS+=(--resume=true)
elif [ -d "$DATASET_ROOT" ]; then
    rm -rf "$DATASET_ROOT"
fi

CAMERAS="$(run_py -m b601.cameras.lerobot_config)" || fail "camera config"
echo
echo "=== EVALUATION: policy drives, you score. E-STOP IN REACH. ==="
echo "  policy   : $POLICY"
echo "  trials   : $TRIALS   cap ${EVAL_TIME_S}s each"
echo "  keys     : RIGHT = end trial (score it), ESC = abort session"
echo

PYTHONNOUSERSITE=1 "$CONDA_BIN/lerobot-record" \
    --robot.type=seeed_b601_rs_follower \
    --robot.port=can0 \
    --robot.id=follower1 \
    --robot.cameras="$CAMERAS" \
    --policy.path="$POLICY" \
    --dataset.repo_id="local/$DATASET_ID" \
    --dataset.root="$DATASET_ROOT" \
    --dataset.single_task="pick up the red block and place it in the bowl" \
    --dataset.num_episodes="$TRIALS" \
    --dataset.fps=30 \
    --dataset.episode_time_s="$EVAL_TIME_S" \
    --dataset.reset_time_s=30 \
    --dataset.push_to_hub=false \
    --display_data=false \
    "${RESUME_ARGS[@]}" "${@:2}"

echo
echo "=== backup ==="
rsync -a "$DATASET_ROOT/" "$BACKUP/$DATASET_ID/"
echo "evaluation episodes backed up"
