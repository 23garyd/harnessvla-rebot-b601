#!/usr/bin/env bash
# V2 corpus recording session — wraps record_session.sh with the v2 dataset,
# the tail-hygiene protocol, and a POST-session drift re-check.
#
# WHY V2 EXISTS (experiment_v2_plan.md has the full design):
#   - v1's episode TAILS taught the policy that a person near the mat means
#     "episode over, go home" (proven by occlusion probes on the frozen
#     policy). The tail-hygiene rules below prevent that.
#   - v1's camera crept up to ~10 px BETWEEN sessions (measured from footage;
#     within-episode it was <1 px). The start gate cannot see drift that
#     happens after it runs, so this wrapper re-checks at session END: a
#     failed exit check quarantines the session's episodes for review
#     instead of silently blending two camera geometries into the corpus.
set -euo pipefail

REPO="${B601_REPO:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
CONDA_PY="${B601_PY:-/home/demo/miniforge3/envs/lerobot/bin/python}"
EPISODES="${1:-}"
[ -n "$EPISODES" ] || { echo "usage: record_session_v2.sh <num_episodes> [--resume=true]" >&2; exit 64; }

cat <<'PROTO'
=== V2 TAIL-HYGIENE PROTOCOL — every episode, no exceptions ===
  1. END THE MOTION, NOT JUST THE TASK: after the block is in the saucer,
     drive the follower back to its park pose, THEN press RIGHT ARROW.
     The episode must end parked, exactly as it began.
  2. STAY OUT OF THE PICTURE while frames are being saved: no reaching in,
     no leaning over the mat until the reset window is announced. Sit at
     the leader station in the same position every episode.
  3. PLACEMENT: anywhere on the mat EXCEPT the red extrapolation zone and
     the five orange interpolation disks (~/Desktop/v2_placement_map.jpg).
     Vary block orientation freely. Spread placements evenly.
  4. Same evening lighting as always. Saucer on its witness mark.
================================================================
PROTO
read -r -p "Protocol read and agreed — ENTER to start the gates "

export B601_DATASET_ID=b601_train_v2
bash "$REPO/b601/setup/record_session.sh" \
    "pick up the red block and place it in the bowl" "$EPISODES" "${@:2}"

echo
echo "=== session-END drift re-check (the start gate cannot see mid-session creep) ==="
run_py() { PYTHONNOUSERSITE=1 PYTHONPATH="$REPO" "$CONDA_PY" "$@"; }
run_py -m b601.cameras.reset || { echo "WARNING: D405 reset failed at exit check" >&2; exit 1; }
run_py -m b601.cameras.capture || { echo "WARNING: capture failed at exit check" >&2; exit 1; }
if run_py -m b601.cameras.reference; then
    echo "  exit drift check clean — this session's episodes recorded under a verified geometry"
else
    echo
    echo "!! EXIT DRIFT CHECK FAILED: the camera moved DURING this session."
    echo "!! Every episode from this session is QUARANTINED until reviewed —"
    echo "!! record the event in the experiment registry before recording more."
    exit 1
fi
