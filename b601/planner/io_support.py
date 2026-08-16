"""Pure support pieces the live io is assembled from.

All four classes are stateful but hardware-free, so every safety property
is exercised in the unpowered suite. The live io composes them; it adds no
logic of its own beyond calling hardware.

StateActionMap — the staging table and fixed poses are OBSERVATION-space
vectors; `send_action` takes ACTION-space. The map is per-joint linear,
fitted on the corpus at 3-tick teleop lag (arm joints r >= 0.998, residual
median < 1 deg; elbow/wrist_flex/wrist_yaw are sign-flipped; the gripper
is a 0.174 scale). Fitted coefficients live in the harness io config
artifact, not in code.

RateLimiter — per-joint |delta| clamp against the PREVIOUS COMMAND, the
same contract as the fork's eval limiter (B601_MAX_ACTION_DELTA). Refuses
to run before reset() anchors it, because "clamped against garbage" is
how the vendor limiter hurt the arm.

MovePlanner — straight joint-space walk to a target under per-tick caps.
Yields absolute waypoints; the caller sends each through the RateLimiter
anyway (belt and suspenders). max_ticks bounds every move.

DivergenceGuard — aborts on SUSTAINED |command - converted state| excess.
Calibrated on the eval recordings: healthy trials <= 5 deg sustained,
grasp-contact episodes <= 7, the C2 table press reached 11. Threshold
15 deg held for 30 consecutive ticks (1 s at 30 Hz). Trips latch: a
tripped guard never un-trips, because resuming motion after an abort is
a human decision.
"""
from __future__ import annotations

import numpy as np


class StateActionMap:
    def __init__(self, config: dict):
        m, c = config.get("m"), config.get("c")
        if m is None or c is None or len(m) != 7 or len(c) != 7:
            raise ValueError("StateActionMap needs 7-dim 'm' and 'c'")
        self._m = np.asarray(m, dtype=float)
        self._c = np.asarray(c, dtype=float)

    def to_action(self, state) -> np.ndarray:
        state = np.asarray(state, dtype=float)
        if state.shape != (7,):
            raise ValueError(f"expected 7-dim state, got {state.shape}")
        return self._m * state + self._c


class RateLimiter:
    def __init__(self, per_tick):
        self._lim = np.abs(np.asarray(per_tick, dtype=float))
        self._prev = None

    def reset(self, reference) -> None:
        self._prev = np.asarray(reference, dtype=float).copy()

    def clamp(self, command) -> np.ndarray:
        if self._prev is None:
            raise RuntimeError("RateLimiter used before reset() — refusing "
                               "to clamp against an unknown reference")
        command = np.asarray(command, dtype=float)
        delta = np.clip(command - self._prev, -self._lim, self._lim)
        self._prev = self._prev + delta
        return self._prev.copy()


class MovePlanner:
    def __init__(self, per_tick, tolerance=1.0, max_ticks=600):
        self._step = np.abs(np.asarray(per_tick, dtype=float))
        self._tol = float(tolerance)
        self._max = int(max_ticks)

    def plan(self, current, target):
        pos = np.asarray(current, dtype=float).copy()
        target = np.asarray(target, dtype=float)
        for _ in range(self._max):
            err = target - pos
            if np.all(np.abs(err) <= self._tol):
                return
            pos = pos + np.clip(err, -self._step, self._step)
            yield pos.copy()
        raise RuntimeError(f"max_ticks ({self._max}) exceeded before arrival")


class DivergenceGuard:
    def __init__(self, threshold=15.0, sustain_ticks=30):
        self._thr = float(threshold)
        self._sustain = int(sustain_ticks)
        self._count = 0
        self.tripped_joint = None

    @property
    def tripped(self) -> bool:
        return self.tripped_joint is not None

    def update(self, command, converted_state) -> bool:
        """True = keep going, False = ABORT (latched)."""
        if self.tripped:
            return False
        gap = np.abs(np.asarray(command, dtype=float)
                     - np.asarray(converted_state, dtype=float))
        worst = int(np.argmax(gap))
        if gap[worst] > self._thr:
            self._count += 1
            if self._count >= self._sustain:
                self.tripped_joint = worst
                return False
        else:
            self._count = 0
        return True
