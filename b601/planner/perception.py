"""Agentview perception for the harness: block pixel and in-saucer check.

Same HSV red gate as every audit and the staging build (single source of
truth for "what counts as the red block"). Both functions fail closed:
bad input reads as "nothing found".

block_pixel: largest red component >= MIN_AREA px, top TOP_MASK rows
masked (desk clutter). NOTE the gate also passes skin (measured: ep24's
end-state "blob" was the operator's hand) — which is why the success
check below is LOCAL to the saucer disk and never global-largest-blob.

saucer_red_fraction: fraction of red pixels inside the fixed saucer disk.
Calibrated on the corpus: placed blocks read 0.30-0.63 (p5 0.302 over the
167 healthy end states), trial starts read 0.000. Threshold 0.20 in the
harness config keeps 1.5x margin below the worst healthy placement.
"""
from __future__ import annotations

import cv2
import numpy as np

# Saturation floor 55 (was 70): measured 2026-08-28 after the glare fix, the
# worst spot on the mat (upper H-zone edge) still washes the block to S=72 —
# a 2-point margin at gate 70. 55 clears it with margin; the mat itself
# cannot reach the red hue band, and the skin-at-reset exposure is unchanged
# (skin passed 70 too — ep24). Recalibrate from v2 corpus at build time.
HSV_LOW1, HSV_HIGH1 = (0, 55, 90), (14, 255, 255)
HSV_LOW2, HSV_HIGH2 = (168, 55, 90), (180, 255, 255)
MIN_AREA = 250
TOP_MASK = 60


def _red_mask(frame_rgb):
    if not isinstance(frame_rgb, np.ndarray) or frame_rgb.ndim != 3 \
            or frame_rgb.shape[2] != 3 or frame_rgb.dtype != np.uint8:
        return None
    hsv = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2HSV)
    return cv2.inRange(hsv, HSV_LOW1, HSV_HIGH1) | \
        cv2.inRange(hsv, HSV_LOW2, HSV_HIGH2)


def block_pixel(frame_rgb):
    """Centroid (x, y) of the largest red component, or None."""
    mask = _red_mask(frame_rgb)
    if mask is None:
        return None
    mask[:TOP_MASK, :] = 0
    cnt, _, stats, cents = cv2.connectedComponentsWithStats(mask)
    best = max((i for i in range(1, cnt) if stats[i, cv2.CC_STAT_AREA] >= MIN_AREA),
               key=lambda i: stats[i, cv2.CC_STAT_AREA], default=None)
    if best is None:
        return None
    return float(cents[best][0]), float(cents[best][1])


def saucer_red_fraction(frame_rgb, center, radius) -> float:
    """Red fraction inside the saucer disk. Local by construction."""
    mask = _red_mask(frame_rgb)
    if mask is None:
        return 0.0
    h, w = mask.shape
    yy, xx = np.mgrid[0:h, 0:w]
    disk = (xx - center[0]) ** 2 + (yy - center[1]) ** 2 <= radius ** 2
    total = int(disk.sum())
    if total == 0:
        return 0.0
    return float(np.count_nonzero(mask[disk])) / total


def wrist_block_pixel(frame_rgb):
    """Centroid of the largest red component in the WRIST frame, or None.

    No top-row mask (the wrist looks at the mat, not the desk) and a larger
    area floor: at pre-grasp range the block is hundreds of px; small red
    flecks are reflections."""
    mask = _red_mask(frame_rgb)
    if mask is None:
        return None
    cnt, _, stats, cents = cv2.connectedComponentsWithStats(mask)
    best = max((i for i in range(1, cnt) if stats[i, cv2.CC_STAT_AREA] >= 400),
               key=lambda i: stats[i, cv2.CC_STAT_AREA], default=None)
    if best is None:
        return None
    return float(cents[best][0]), float(cents[best][1])
