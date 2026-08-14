"""Wrist-camera grasp verifier: is the block actually in the gripper?

Two independent cues, ANDed — both must say yes:

  image cue    A held block hangs inches below the D405 lens, so it shows as
               a large red region in the bottom half of the wrist frame that
               reaches the bottom edge. A block still on the table shows
               smaller, higher, and clear of the bottom strip.
  gripper cue  The gripper position must sit in the hold band measured from
               the corpus: closed onto the block, not open, and not closed
               past it onto air.

Fail-closed by construction: a bad frame, a missing gripper reading or any
internal doubt is a NO with a reason — never an exception mid-harness and
never a YES. Thresholds live in a JSON config artifact so they are pinned
experiment state, not code.
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

_REQUIRED_KEYS = (
    "min_red_fraction", "min_bottom_fraction",
    "gripper_hold_min", "gripper_hold_max",
    "hsv_low1", "hsv_high1", "hsv_low2", "hsv_high2",
)

_ROI_TOP = 0.5      # bottom-half ROI for the main red fraction
_STRIP_TOP = 0.85   # bottom strip a held block must reach


@dataclass(frozen=True)
class GraspVerdict:
    held: bool
    red_fraction: float
    bottom_fraction: float
    gripper_ok: bool
    reason: str


class GraspVerifier:
    def __init__(self, config: dict):
        missing = [k for k in _REQUIRED_KEYS if k not in config]
        if missing:
            raise ValueError(f"config missing keys: {missing}")
        lo = float(config["gripper_hold_min"])
        hi = float(config["gripper_hold_max"])
        if not lo < hi:
            raise ValueError(f"gripper hold band inverted: [{lo}, {hi}]")
        self._min_red = float(config["min_red_fraction"])
        self._min_bottom = float(config["min_bottom_fraction"])
        self._grip_lo, self._grip_hi = lo, hi
        self._hsv = tuple(
            np.array(config[k], dtype=np.uint8)
            for k in ("hsv_low1", "hsv_high1", "hsv_low2", "hsv_high2")
        )

    @classmethod
    def load(cls, path: str) -> "GraspVerifier":
        import json
        with open(path) as f:
            return cls(json.load(f))

    def verify(self, frame_rgb, gripper_pos) -> GraspVerdict:
        no = lambda reason, red=0.0, bot=0.0, gok=False: GraspVerdict(
            False, red, bot, gok, reason)

        if not isinstance(frame_rgb, np.ndarray) or frame_rgb.ndim != 3 \
                or frame_rgb.shape[2] != 3 or frame_rgb.dtype != np.uint8:
            return no("invalid frame")
        if gripper_pos is None or not np.isfinite(gripper_pos):
            return no("no gripper reading")

        gok = self._grip_lo <= float(gripper_pos) <= self._grip_hi

        lo1, hi1, lo2, hi2 = self._hsv
        hsv = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2HSV)
        mask = cv2.inRange(hsv, lo1, hi1) | cv2.inRange(hsv, lo2, hi2)
        h = mask.shape[0]
        roi = mask[int(h * _ROI_TOP):, :]
        strip = mask[int(h * _STRIP_TOP):, :]
        red = float(np.count_nonzero(roi)) / roi.size
        bot = float(np.count_nonzero(strip)) / strip.size

        if not gok:
            return no("gripper outside hold band", red, bot, False)
        if red < self._min_red:
            return no("red below threshold", red, bot, True)
        if bot < self._min_bottom:
            return no("red not reaching bottom edge", red, bot, True)
        return GraspVerdict(True, red, bot, True, "held")
