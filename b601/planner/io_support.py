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


class ServoController:
    """Wrist-image servo toward the demonstrated pre-grasp view.

    After the open-loop stage, the block's centroid in the wrist frame is
    driven to the corpus target using the measured coupling: pan on image x
    (v2 per-joint fit: -12.2 px/deg approach, -14.3 deep), ELBOW ALONE on
    image y (+13.3 approach, +10.2 deep, R2 0.48-0.54). The old lift+elbow
    'reach' split self-cancelled: lift and elbow OPPOSE on image y
    (-3.75 vs +10.23 px/deg at depth), which is why the 2026-08-28 recovery
    shakedown burned 40+ deg of joint motion for ~0 px of y progress.
    Feedback each tick forgives the fit's noise — only the signs must hold.

    Best-effort by contract: returns None to STOP (converged, block lost,
    stalled, or budget spent) and the caller proceeds either way. Danger is
    the DivergenceGuard's job, not this controller's.
    """

    def __init__(self, target, tolerance_px, gain, max_step_deg,
                 max_total_deg, max_ticks, stall_ticks, jx_pan, jy_elbow):
        self._target = (float(target[0]), float(target[1]))
        self._tol = float(tolerance_px)
        self._gain = float(gain)
        self._max_step = float(max_step_deg)
        self._budget = [float(max_total_deg), float(max_total_deg)]
        self._max_ticks = int(max_ticks)
        self._stall_ticks = int(stall_ticks)
        self._j = (float(jx_pan), float(jy_elbow))
        self._ticks = 0
        self._best_err = None
        self._stall = 0
        self.converged = False

    def step(self, centroid):
        """centroid (cx, cy) or None -> (d_pan, d_elbow) in degrees, or
        None to stop. Latches after any stop."""
        if self.converged or self._ticks >= self._max_ticks:
            return None
        if centroid is None:
            return None
        self._ticks += 1
        ex = self._target[0] - float(centroid[0])
        ey = self._target[1] - float(centroid[1])
        if abs(ex) <= self._tol and abs(ey) <= self._tol:
            self.converged = True
            return None
        err = (ex * ex + ey * ey) ** 0.5
        if self._best_err is None or err < self._best_err - 1.0:
            self._best_err = min(err, self._best_err or err)
            self._stall = 0
        else:
            self._stall += 1
            if self._stall >= self._stall_ticks:
                return None
        d_pan = max(-self._max_step,
                    min(self._max_step, ex / self._j[0] * self._gain))
        d_elbow = max(-self._max_step,
                      min(self._max_step, ey / self._j[1] * self._gain))
        d_pan = max(-self._budget[0], min(self._budget[0], d_pan))
        d_elbow = max(-self._budget[1], min(self._budget[1], d_elbow))
        if abs(d_pan) < 1e-9 and abs(d_elbow) < 1e-9:
            return None
        self._budget[0] -= abs(d_pan)
        self._budget[1] -= abs(d_elbow)
        return d_pan, d_elbow
