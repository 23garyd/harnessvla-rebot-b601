"""Per-trial drift gate for policy/harness sessions.

The session-start gate cannot see drift that happens after it runs.
Measured on v1 footage: within an episode the mount holds to <1 px, but
BETWEEN same-evening sessions it crept up to ~10 px while every start gate
passed — enough to bias staging by ~1 cm and quietly change what the policy
sees. This check runs between trials using frames from the ROBOT'S OWN open
camera (the reference module's grabber would fight the robot for the
device), through the same phantom-rejecting aggregation and the same
compare as the session gate.
"""
from __future__ import annotations

from b601.cameras.reference import (
    DriftError,
    compare_landmarks,
    detect_landmarks,
    load_reference,
    observed_landmarks,
)

CAMERA = "agentview"


def trial_drift_check(get_observation, reference=None, burst=10):
    """-> DriftReport for the agentview mount, from live robot frames.

    `get_observation` is the robot's observation callable; only the
    agentview frame is consumed. Raises DriftError if frames or the
    reference are unavailable — a gate that cannot run must not pass.
    """
    ref = reference if reference is not None else load_reference()
    if CAMERA not in ref.cameras:
        raise DriftError(f"reference records no landmarks for {CAMERA}")
    per_frame = []
    for _ in range(int(burst)):
        frame = get_observation().get(CAMERA)
        if frame is None:
            raise DriftError(
                f"{CAMERA}: robot observation carried no frame — "
                f"the mount could not be verified")
        per_frame.append(detect_landmarks(frame))
    current = observed_landmarks(per_frame)
    return compare_landmarks(CAMERA, ref.cameras[CAMERA], current,
                             ref.tolerance_px)
