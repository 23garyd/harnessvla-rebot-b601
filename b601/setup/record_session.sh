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
#   2a. reset         MEASURED: the D405 (fw 5.12.14.100) streams exactly ONE
#                     pipeline session per hardware reset, so every consumer
#                     of a session gets a reset immediately before it.
#                     Preflight gets one (whatever ran earlier in the day left
#                     the camera dead), and lerobot-record gets one (preflight
#                     itself consumed a session — which is precisely how
#                     recording attempt 4 timed out on a camera preflight had
#                     just passed)
#   3. preflight      cameras are alive, in sync, and no mount has drifted
#   4. reset+capture  the record process's own fresh session — and the reset
#                     wipes the sensor options, so capture runs again.
#                     (Options set without a pipeline do not consume the
#                     session and persist into the next one; measured, see
#                     b601/cameras/reset.py)
#   5. backup check   the destination exists and is writable BEFORE recording,
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
# /mnt/nvme3 is an fstab mount (UUID=b0b0d284…, nofail) since 2026-08-10 —
# it survives reboots, unlike the udisks /media/demo path it replaces.
BACKUP="${B601_BACKUP:-/mnt/nvme3/b601}"

TASK="${1:-}"
EPISODES="${2:-1}"
[ -n "$TASK" ] || { echo "usage: record_session.sh \"<task description>\" [num_episodes]" >&2; exit 64; }

DATASET_ID="${B601_DATASET_ID:-b601_pilot}"
DATASET_ROOT="${B601_DATASET_ROOT:-$REPO/datasets/$DATASET_ID}"

fail() { echo "GATE FAILED: $*" >&2; exit 1; }
run_py() { PYTHONNOUSERSITE=1 PYTHONPATH="$REPO" "$CONDA_PY" "$@"; }

echo "=== 1/5  experiment identity (pin_check) ==="
B601_PY="$CONDA_PY" bash "$REPO/b601/setup/pin_check.sh" \
    || fail "pins do not verify. Recording now would produce episodes that cannot be attributed to a configuration — the whole point of the regime. Re-record pins ONLY if the change was deliberate, with an experiment-registry entry"

echo "=== 2/5  fresh D405 session, then the manifest onto the cameras ==="
run_py -m b601.cameras.reset \
    || fail "the D405 did not come back from its hardware reset — see the one-session-per-reset entry in risk_log.md"
run_py -m b601.cameras.capture \
    || fail "cameras could not be configured as cameras.json describes"

echo "=== 3/5  preflight (liveness, sync, mount drift) ==="
run_py -m b601.cameras.preflight \
    || fail "preflight. Do not record until this passes"

echo "=== 4/5  hand lerobot-record a FRESH D405 session ==="
run_py -m b601.cameras.reset \
    || fail "the D405 did not come back from its hardware reset. lerobot-record would open the dead post-preflight session and time out with zero frames"
run_py -m b601.cameras.capture \
    || fail "re-applying the manifest after the reset failed — the reset wiped the sensor options, so recording now would run under auto exposure"

echo "=== 5/5  backup destination ==="
[ -d "$BACKUP" ] || fail "backup directory missing: $BACKUP"
touch "$BACKUP/.write_test" 2>/dev/null || fail "backup directory is not writable: $BACKUP — a teleop session cannot be regenerated, so this is checked BEFORE recording"
rm -f "$BACKUP/.write_test"
echo "  $BACKUP is writable ($(df -h "$BACKUP" | awk 'NR==2{print $4}') free)"

# A run that aborted after LeRobotDataset.create() leaves a skeleton behind,
# and create() uses mkdir(exist_ok=False), so the next attempt dies with a bare
# FileExistsError. Clear the skeleton, but NEVER anything holding episodes: a
# teleop session cannot be regenerated, and an accidental clobber here is the
# single most expensive mistake available in this project.
#
# APPENDING is the exception: pass --resume=true (forwarded to lerobot-record,
# which loads the existing dataset and sanity-checks compatibility) and the
# guard inverts — existing episodes are then EXPECTED, not a hazard.
RESUME=false
for arg in "${@:3}"; do [ "$arg" = "--resume=true" ] && RESUME=true; done
if [ -d "$DATASET_ROOT" ]; then
    EXISTING="$(find "$DATASET_ROOT" \( -name '*.parquet' -o -name '*.mp4' \) 2>/dev/null | head -1)"
    if [ -n "$EXISTING" ] && ! $RESUME; then
        fail "$DATASET_ROOT already holds recorded episodes (e.g. $EXISTING). Refusing to touch it — pass --resume=true to append, set B601_DATASET_ID to a new name, or move the existing dataset aside deliberately"
    fi
    if [ -z "$EXISTING" ]; then
        if $RESUME; then
            fail "--resume=true but $DATASET_ROOT holds no episodes to resume — drop the flag for a fresh recording"
        fi
        echo "  clearing an empty dataset skeleton from an aborted run (no episode data present)"
        rm -rf "$DATASET_ROOT"
    else
        echo "  resuming: appending to $(find "$DATASET_ROOT" -name '*.parquet' -path '*/data/*' | wc -l) existing data file(s) in $DATASET_ROOT"
    fi
elif $RESUME; then
    fail "--resume=true but $DATASET_ROOT does not exist — drop the flag for a fresh recording"
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
