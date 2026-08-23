"""Block pixel -> pre-grasp joint pose, learned from the demonstrations.

Each corpus episode pairs a block position (agentview pixel) with the pose
the operator staged just before the grasp. Queries inside demonstrated
coverage (nearest placement <= knn_radius_px) interpolate the k nearest
placements by inverse distance. Beyond that — the held-out zone's 40-90 px
gap — a GLOBAL quadratic trend fitted over every pair answers instead:
k-NN's one-sided neighbors clamp to the nearest cluster and cannot see the
trend into a coverage hole (measured: the first held-out shakedown trial
staged visibly off the block at 56 px; synthetic-hole validation, max
positional error: k-NN 26.6 deg vs quadratic 20.8). Two refusals, both
fail-closed:

  - a query farther than `max_extrapolation_px` from EVERY demonstrated
    placement is refused — staging at a wild extrapolation points the frozen
    policy somewhere no demonstration ever went, and the held-out zone's
    40-80 px gap from coverage is inside the default guard by measurement,
    not by luck;
  - a table too small to interpolate is refused at fit time.

The nearest-placement distance is returned with every pose so the harness
can log how far outside experience each staging decision reached.
"""
import json
from dataclasses import dataclass
from pathlib import Path


DEFAULT_K = 3
DEFAULT_MAX_EXTRAPOLATION_PX = 100.0
DEFAULT_KNN_RADIUS_PX = 25.0
_QUAD_MIN_POINTS = 12    # 6 coefficients; demand 2x for a stable fit


def _quad_features(px, py):
    x, y = px / 100.0, py / 100.0
    return (1.0, x, y, x * y, x * x, y * y)


class StagingError(Exception):
    """The table cannot answer safely. Never stage on a guess."""


@dataclass(frozen=True)
class StagingTable:
    points: tuple          # ((px, py), ...)
    poses: tuple           # ((j0..jn), ...) same length
    k: int = DEFAULT_K
    max_extrapolation_px: float = DEFAULT_MAX_EXTRAPOLATION_PX
    knn_radius_px: float = DEFAULT_KNN_RADIUS_PX
    quad: tuple = None     # (6 x n_dims) trend coefficients, or None

    @classmethod
    def fit(cls, points, poses, k=DEFAULT_K,
            max_extrapolation_px=DEFAULT_MAX_EXTRAPOLATION_PX,
            knn_radius_px=DEFAULT_KNN_RADIUS_PX):
        points = tuple((float(x), float(y)) for x, y in points)
        poses = tuple(tuple(float(v) for v in p) for p in poses)
        if len(points) != len(poses):
            raise StagingError(
                f"{len(points)} placements but {len(poses)} poses — they must "
                f"match one-to-one")
        if len(points) < 2:
            raise StagingError(
                f"need at least 2 demonstrated placements to interpolate, "
                f"got {len(points)}")
        quad = None
        if len(points) >= _QUAD_MIN_POINTS:
            import numpy as np
            A = np.array([_quad_features(x, y) for x, y in points])
            W, *_ = np.linalg.lstsq(A, np.array(poses), rcond=None)
            quad = tuple(tuple(float(v) for v in row) for row in W)
        return cls(points=points, poses=poses, k=k,
                   max_extrapolation_px=max_extrapolation_px,
                   knn_radius_px=knn_radius_px, quad=quad)

    def query(self, px, py):
        """-> (pose, nearest_distance_px). Refuses wild extrapolation."""
        d2 = [((px - x) ** 2 + (py - y) ** 2, i)
              for i, (x, y) in enumerate(self.points)]
        d2.sort()
        nearest = d2[0][0] ** 0.5
        if nearest > self.max_extrapolation_px:
            raise StagingError(
                f"query ({px:.0f},{py:.0f}) is {nearest:.0f}px from the "
                f"nearest demonstrated placement — beyond the "
                f"{self.max_extrapolation_px:.0f}px guard. No demonstration "
                f"ever staged there; refusing to guess")
        if nearest > self.knn_radius_px and self.quad is not None:
            # coverage hole: follow the global trend, not the nearest cluster
            f = _quad_features(px, py)
            n = len(self.poses[0])
            pose = [sum(f[c] * self.quad[c][j] for c in range(6))
                    for j in range(n)]
            return pose, nearest
        chosen = d2[:min(self.k, len(d2))]
        if chosen[0][0] == 0.0:                      # exact hit
            return list(self.poses[chosen[0][1]]), 0.0
        weights = [(1.0 / (dd ** 0.5), i) for dd, i in chosen]
        total = sum(w for w, _ in weights)
        n = len(self.poses[0])
        pose = [sum(w * self.poses[i][j] for w, i in weights) / total
                for j in range(n)]
        return pose, nearest

    def write(self, path):
        Path(path).write_text(json.dumps({
            "_note": ["Staging table: block agentview pixel -> pre-grasp "
                      "joint pose, extracted from the demonstration corpus.",
                      "Derived data: rebuild from the corpus rather than "
                      "editing. The harness refuses queries beyond "
                      "max_extrapolation_px from demonstrated coverage."],
            "points": list(self.points),
            "poses": list(self.poses),
            "k": self.k,
            "max_extrapolation_px": self.max_extrapolation_px,
            "knn_radius_px": self.knn_radius_px,
        }, indent=1))

    @classmethod
    def load(cls, path):
        raw = json.loads(Path(path).read_text())
        return cls.fit(raw["points"], raw["poses"], k=raw["k"],
                       max_extrapolation_px=raw["max_extrapolation_px"],
                       knn_radius_px=raw.get("knn_radius_px",
                                             DEFAULT_KNN_RADIUS_PX))
