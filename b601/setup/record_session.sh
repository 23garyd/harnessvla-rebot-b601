#!/usr/bin/env bash
# Record a teleoperated session, with the gates in front of it.
#
# WHY A WRAPPER AND NOT A COMMAND IN THE RUNBOOK. A teleop session cannot be
# regenerated. Every check here is cheap; discovering afterwards that the
# cameras ran under auto exposure, or that a mount had shifted, or that nobody
# can say which lerobot produced the episodes, costs the session. So the gates
# run in order and a failure stops the recording rather than warning about it.
#
#   1. pin_check      the experiment is IDENTIFIED — interpreter, lerobot
#                     codebase, placo, plugin, URDF, cameras, calibration
#   2. capture        the manifest's fixed exposure/gain are ON THE DEVICES.
#                     LeRobot's camera configs carry no exposure field, so
#                     without this the session records under auto exposure no
#                     matter what cameras.json says
#   3. preflight      cameras are alive, in sync, and no mount has drifted
#   4. backup check   the destination exists and is writable BEFORE recording,
#                     not after
#
# The camera argument is DERIVED from cameras.json rather than typed here, so
# the manifest cannot drift from what was actually recorded.
#
# WHAT THIS DOES NOT COVER: it cannot see the operator. Whether the
# demonstration was any good, whether the object was in the right place, and
# whether the arm was about to hit something are all human judgements.
set -euo pipefail

REPO="${B601_REPO:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
CONDA_PY="${B601_PY:-/home/demo/miniforge3/envs/lerobot/bin/python}"
CONDA_BIN="$(dirname "$CONDA_PY")"
BACKUP="${B601_BACKUP:-/media/demo/b0b0d284-79d6-4291-93ad-f27ef2f77022/b601}"

TASK="${1:-}"
EPISODES="${2:-1}"
[ -n "$TASK" ] || { echo "usage: record_session.sh \"<task description>\" [num_episodes]" >&2; exit 64; }

DATASET_ID="${B601_DATASET_ID:-b601_pilot}"
DATASET_ROOT="${B601_DATASET_ROOT:-$REPO/datasets/$DATASET_ID}"

fail() { echo "GATE FAILED: $*" >&2; exit 1; }
run_py() { PYTHONNOUSERSITE=1 PYTHONPATH="$REPO" "$CONDA_PY" "$@"; }

echo "=== 1/4  experiment identity (pin_check) ==="
B601_PY="$CONDA_PY" bash "$REPO/b601/setup/pin_check.sh" \
    || fail "pins do not verify. Recording now would produce episodes that cannot be attributed to a configuration — the whole point of the regime. Re-record pins ONLY if the change was deliberate, with an experiment-registry entry"

echo "=== 2/4  apply the manifest to the cameras ==="
run_py -m b601.cameras.capture \
    || fail "cameras could not be configured as cameras.json describes"

echo "=== 3/4  preflight (liveness, sync, mount drift) ==="
run_py -m b601.cameras.preflight \
    || fail "preflight. Do not record until this passes"

echo "=== 4/4  backup destination ==="
[ -d "$BACKUP" ] || fail "backup directory missing: $BACKUP"
touch "$BACKUP/.write_test" 2>/dev/null || fail "backup directory is not writable: $BACKUP — a teleop session cannot be regenerated, so this is checked BEFORE recording"
rm -f "$BACKUP/.write_test"
echo "  $BACKUP is writable ($(df -h "$BACKUP" | awk 'NR==2{print $4}') free)"

# A run that aborted after LeRobotDataset.create() leaves a skeleton behind,
# and create() uses mkdir(exist_ok=False), so the next attempt dies with a bare
# FileExistsError. Clear the skeleton, but NEVER anything holding episodes: a
# teleop session cannot be regenerated, and an accidental clobber here is the
# single most expensive mistake available in this project.
if [ -d "$DATASET_ROOT" ]; then
    EXISTING="$(find "$DATASET_ROOT" \( -name '*.parquet' -o -name '*.mp4' \) 2>/dev/null | head -1)"
    if [ -n "$EXISTING" ]; then
        fail "$DATASET_ROOT already holds recorded episodes (e.g. $EXISTING). Refusing to touch it — set B601_DATASET_ID to a new name, or move the existing dataset aside deliberately"
    fi
    echo "  clearing an empty dataset skeleton from an aborted run (no episode data present)"
    rm -rf "$DATASET_ROOT"
fi

CAMERAS="$(run_py -m b601.cameras.lerobot_config)" || fail "could not derive the camera argument from cameras.json"
echo
echo "=== recording ==="
echo "  task      : $TASK"
echo "  episodes  : $EPISODES"
echo "  dataset   : $DATASET_ROOT"
echo "  cameras   : $(echo "$CAMERAS" | "$CONDA_PY" -c 'import json,sys; print(", ".join(json.load(sys.stdin)))')"
echo

PYTHONNOUSERSITE=1 "$CONDA_BIN/lerobot-record" \
    --robot.type=seeed_b601_rs_follower \
    --robot.port=can0 \
    --robot.id=follower1 \
    --robot.cameras="$CAMERAS" \
    --teleop.type=rebot_arm_102_leader \
    --teleop.port=/dev/ttyUSB0 \
    --teleop.id=rebot_arm_102_leader \
    --dataset.repo_id="local/$DATASET_ID" \
    --dataset.root="$DATASET_ROOT" \
    --dataset.single_task="$TASK" \
    --dataset.num_episodes="$EPISODES" \
    --dataset.fps=30 \
    --dataset.push_to_hub=false \
    --display_data=false \
    "${@:3}"

echo
echo "=== backup (the dataset is irreplaceable) ==="
rsync -a --info=stats1 "$DATASET_ROOT/" "$BACKUP/$DATASET_ID/" \
    || fail "BACKUP FAILED — the episodes exist in one place only. Fix before recording more"
echo "  backed up -> $BACKUP/$DATASET_ID"
echo
echo "NEXT: replay before trusting these episodes —"
echo "  $CONDA_BIN/lerobot-replay --robot.type=seeed_b601_rs_follower \\"
echo "      --robot.port=can0 --robot.id=follower1 \\"
echo "      --dataset.repo_id=local/$DATASET_ID --dataset.root=$DATASET_ROOT --dataset.episode=0"
echo "The Day-5 gate is 9 of 10 episodes replaying correctly, which is a"
echo "judgement only a human watching the arm can make."
