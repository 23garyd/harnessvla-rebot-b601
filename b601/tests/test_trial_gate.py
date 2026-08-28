"""Per-trial drift gate: verify the agentview mount against the pinned
reference using frames from the ROBOT'S OWN open camera, between trials.

Why it exists (v2): the session-start gate cannot see drift that happens
after it runs, and v1 footage shows the mount creeping up to ~10 px between
same-evening sessions while every start gate passed. A trial that begins on
a drifted camera silently invalidates its staging and its comparability.

The check must reuse the reference module's phantom rejection: the cutting
mat hallucinates ArUco ids that wander hundreds of px (measured), and a
naive per-frame check would fail forever on them.
"""
import numpy as np
import pytest
import cv2

from b601.cameras.reference import DriftError
from b601.planner.trial_gate import trial_drift_check


def make_frame(tag_positions, size=(480, 640)):
    """Grey frame with real DICT_4X4_50 markers drawn at given centres."""
    img = np.full((size[0], size[1], 3), 140, dtype=np.uint8)
    adict = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    for tid, (cx, cy) in tag_positions.items():
        marker = cv2.aruco.generateImageMarker(adict, tid, 48)
        # white quiet zone so the border decodes
        x0, y0 = int(cx) - 24, int(cy) - 24
        img[y0 - 6:y0 + 54, x0 - 6:x0 + 54] = 255
        img[y0:y0 + 48, x0:x0 + 48] = cv2.cvtColor(marker, cv2.COLOR_GRAY2BGR)
    return img


REF = {6: (91.0, 328.0), 7: (117.0, 108.0), 9: (522.0, 146.0),
       10: (480.0, 363.0)}


class FakeRef:
    cameras = {"agentview": REF}
    tolerance_px = 3.0


def obs_source(tag_positions):
    frame = make_frame(tag_positions)
    return lambda: {"agentview": frame}


class TestTrialGate:
    def test_clean_mount_passes(self):
        report = trial_drift_check(obs_source(REF), reference=FakeRef(),
                                   burst=6)
        assert report.passed
        assert report.landmarks_checked == 4

    def test_shifted_mount_fails(self):
        shifted = {t: (x + 6.0, y + 6.0) for t, (x, y) in REF.items()}
        report = trial_drift_check(obs_source(shifted), reference=FakeRef(),
                                   burst=6)
        assert not report.passed
        assert report.median_displacement_px > 3.0

    def test_missing_landmark_fails(self):
        partial = {t: p for t, p in REF.items() if t != 9}
        report = trial_drift_check(obs_source(partial), reference=FakeRef(),
                                   burst=6)
        assert not report.passed
        assert 9 in report.missing

    def test_no_frames_raises(self):
        with pytest.raises(DriftError):
            trial_drift_check(lambda: {"agentview": None},
                              reference=FakeRef(), burst=6)
