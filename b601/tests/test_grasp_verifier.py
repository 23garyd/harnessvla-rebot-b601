"""Grasp verifier: wrist-camera + gripper-state yes/no for "is the block in
the gripper". Fail-closed: any doubt — bad frame, missing gripper reading,
malformed config — is a NO, never an exception mid-harness and never a YES.

The image cue and the gripper cue are ANDed: a held block must show red in
the lower part of the wrist frame reaching the bottom edge (it is inches
from the lens, gripped below it), AND the gripper must sit in the hold band
measured from the corpus (closed on the block, not open, not closed on air).
"""
import json

import numpy as np
import pytest

from b601.planner.grasp_verifier import GraspVerifier, GraspVerdict

CONFIG = {
    "min_red_fraction": 0.10,      # of bottom-half ROI
    "min_bottom_fraction": 0.05,   # of bottom strip (y >= 85%)
    "gripper_hold_min": 100.0,
    "gripper_hold_max": 220.0,
    "hsv_low1": [0, 70, 90], "hsv_high1": [14, 255, 255],
    "hsv_low2": [168, 70, 90], "hsv_high2": [180, 255, 255],
}
HOLD = 160.0   # inside band
OPEN = 260.0   # outside band (gripper open)
AIR = 40.0     # outside band (closed on nothing)


def frame(red_rows=None, red_cols=None):
    """Green 480x640 RGB frame with an optional pure-red rectangle."""
    img = np.zeros((480, 640, 3), dtype=np.uint8)
    img[:, :, 1] = 120  # green mat backdrop
    if red_rows is not None:
        r0, r1 = red_rows
        c0, c1 = red_cols
        img[r0:r1, c0:c1] = (255, 30, 30)
    return img


def make():
    return GraspVerifier(dict(CONFIG))


class TestVerdicts:
    def test_held_block_is_yes(self):
        # big red region in the bottom half, touching the bottom edge
        v = make().verify(frame((300, 480), (150, 500)), HOLD)
        assert isinstance(v, GraspVerdict)
        assert v.held is True

    def test_no_red_is_no(self):
        v = make().verify(frame(), HOLD)
        assert v.held is False
        assert v.red_fraction == 0.0

    def test_red_only_in_top_half_is_no(self):
        # block visible on the table ahead, not in the gripper
        v = make().verify(frame((40, 200), (200, 400)), HOLD)
        assert v.held is False

    def test_red_not_reaching_bottom_edge_is_no(self):
        # red in the bottom half but clear of the bottom strip
        v = make().verify(frame((250, 380), (150, 500)), HOLD)
        assert v.held is False

    def test_gripper_open_is_no_even_with_red(self):
        v = make().verify(frame((300, 480), (150, 500)), OPEN)
        assert v.held is False
        assert v.gripper_ok is False

    def test_gripper_closed_on_air_is_no_even_with_red(self):
        v = make().verify(frame((300, 480), (150, 500)), AIR)
        assert v.held is False
        assert v.gripper_ok is False


class TestFailClosed:
    def test_none_frame_is_no_not_exception(self):
        v = make().verify(None, HOLD)
        assert v.held is False
        assert "frame" in v.reason

    def test_wrong_shape_is_no(self):
        v = make().verify(np.zeros((480, 640), dtype=np.uint8), HOLD)
        assert v.held is False

    def test_wrong_dtype_is_no(self):
        v = make().verify(np.zeros((480, 640, 3), dtype=np.float32), HOLD)
        assert v.held is False

    def test_missing_gripper_reading_is_no(self):
        v = make().verify(frame((300, 480), (150, 500)), None)
        assert v.held is False
        assert "gripper" in v.reason


class TestConfig:
    def test_missing_key_refused_at_construction(self):
        bad = dict(CONFIG)
        del bad["gripper_hold_min"]
        with pytest.raises(ValueError, match="gripper_hold_min"):
            GraspVerifier(bad)

    def test_inverted_band_refused(self):
        bad = dict(CONFIG)
        bad["gripper_hold_min"], bad["gripper_hold_max"] = 220.0, 100.0
        with pytest.raises(ValueError, match="band"):
            GraspVerifier(bad)

    def test_load_round_trip(self, tmp_path):
        p = tmp_path / "verifier.json"
        p.write_text(json.dumps(CONFIG))
        v = GraspVerifier.load(str(p)).verify(frame((300, 480), (150, 500)), HOLD)
        assert v.held is True
