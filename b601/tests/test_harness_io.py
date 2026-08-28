"""Support pieces the live io is assembled from — each pure and testable:

StateActionMap   state-space pose -> action-space command (per-joint linear,
                 fitted on the corpus: arm joints r>=0.998, elbow/wrist_flex/
                 wrist_yaw sign-flipped, gripper 0.174 scale)
RateLimiter      per-joint |delta| clamp against the PREVIOUS COMMAND —
                 same contract as the fork's eval limiter
MovePlanner      joint-space interpolation to a target under per-tick caps;
                 refuses to start from an unknown state
DivergenceGuard  aborts on SUSTAINED |command - converted state| excess
                 (threshold 15 deg / 30 ticks: healthy eval trials <=7,
                 the C2 press reached 11, the guard exists for exactly that)
perception       block pixel + in-saucer red fraction (local disk — a hand
                 elsewhere in the frame must not matter; measured on ep24)
"""
import numpy as np
import pytest

from b601.planner.io_support import (
    StateActionMap, RateLimiter, MovePlanner, DivergenceGuard,
)
from b601.planner import perception

IDENTITY = {"m": [1, 1, 1, 1, 1, 1, 1], "c": [0, 0, 0, 0, 0, 0, 0]}
MIRROR = {"m": [1.0, 0.97, -1.024, -1.002, -1.022, 1.002, 0.174],
          "c": [0.17, 0.37, -1.08, -1.45, 0.04, 0.01, -2.62]}


class TestStateActionMap:
    def test_identity_map_round_trip(self):
        sam = StateActionMap(IDENTITY)
        v = np.array([1.0, 2, 3, 4, 5, 6, 7])
        assert np.allclose(sam.to_action(v), v)

    def test_mirrored_joints_flip_sign(self):
        sam = StateActionMap(MIRROR)
        out = sam.to_action(np.array([0.0, 0, 100, 100, 100, 0, 0]))
        assert out[2] < -90 and out[3] < -90 and out[4] < -90

    def test_wrong_length_refused(self):
        with pytest.raises(ValueError):
            StateActionMap({"m": [1, 2], "c": [0, 0]}).to_action(np.zeros(7))
        with pytest.raises(ValueError):
            StateActionMap(IDENTITY).to_action(np.zeros(5))


class TestRateLimiter:
    def test_step_within_limit_passes_unchanged(self):
        rl = RateLimiter(np.full(7, 2.0))
        rl.reset(np.zeros(7))
        out = rl.clamp(np.full(7, 1.5))
        assert np.allclose(out, 1.5)

    def test_step_beyond_limit_is_clamped_per_joint(self):
        rl = RateLimiter(np.array([1.0, 2.0, 1, 1, 1, 1, 9]))
        rl.reset(np.zeros(7))
        out = rl.clamp(np.array([5.0, -5.0, 0, 0, 0, 0, 5.0]))
        assert out[0] == 1.0 and out[1] == -2.0 and out[6] == 5.0

    def test_clamps_against_previous_command_not_state(self):
        rl = RateLimiter(np.full(7, 1.0))
        rl.reset(np.zeros(7))
        rl.clamp(np.full(7, 5.0))          # -> 1.0
        out = rl.clamp(np.full(7, 5.0))    # -> 2.0 (walks, never jumps)
        assert np.allclose(out, 2.0)

    def test_unreset_limiter_refuses(self):
        rl = RateLimiter(np.full(7, 1.0))
        with pytest.raises(RuntimeError):
            rl.clamp(np.zeros(7))


class TestMovePlanner:
    def test_reaches_target_and_stops(self):
        mp = MovePlanner(per_tick=np.full(7, 2.0), tolerance=0.5)
        steps = list(mp.plan(np.zeros(7), np.full(7, 5.0)))
        assert len(steps) == 3                      # 2, 4, 5
        assert np.allclose(steps[-1], 5.0)

    def test_no_steps_when_already_there(self):
        mp = MovePlanner(per_tick=np.full(7, 2.0), tolerance=0.5)
        assert list(mp.plan(np.full(7, 5.0), np.full(7, 5.2))) == []

    def test_max_ticks_bounds_the_walk(self):
        mp = MovePlanner(per_tick=np.full(7, 0.001), tolerance=0.1,
                         max_ticks=50)
        with pytest.raises(RuntimeError, match="max_ticks"):
            list(mp.plan(np.zeros(7), np.full(7, 100.0)))


class TestDivergenceGuard:
    def test_quiet_within_threshold(self):
        g = DivergenceGuard(threshold=15.0, sustain_ticks=30)
        for _ in range(200):
            assert g.update(np.full(6, 10.0), np.zeros(6)) is True

    def test_transient_spike_does_not_abort(self):
        g = DivergenceGuard(threshold=15.0, sustain_ticks=30)
        for _ in range(29):
            assert g.update(np.full(6, 50.0), np.zeros(6)) is True
        assert g.update(np.zeros(6), np.zeros(6)) is True   # recovered
        for _ in range(29):
            assert g.update(np.full(6, 50.0), np.zeros(6)) is True

    def test_sustained_excess_aborts(self):
        g = DivergenceGuard(threshold=15.0, sustain_ticks=30)
        ok = True
        for _ in range(30):
            ok = g.update(np.full(6, 16.0), np.zeros(6))
        assert ok is False
        assert g.tripped_joint is not None

    def test_stays_tripped(self):
        g = DivergenceGuard(threshold=15.0, sustain_ticks=2)
        g.update(np.full(6, 99.0), np.zeros(6))
        g.update(np.full(6, 99.0), np.zeros(6))
        assert g.update(np.zeros(6), np.zeros(6)) is False


def synth(red_rect=None):
    img = np.zeros((480, 640, 3), dtype=np.uint8)
    img[:, :, 1] = 120
    if red_rect:
        r0, r1, c0, c1 = red_rect
        img[r0:r1, c0:c1] = (255, 30, 30)
    return img


class TestPerception:
    def test_block_pixel_found_at_centroid(self):
        p = perception.block_pixel(synth((280, 340, 180, 240)))
        assert p is not None
        assert abs(p[0] - 210) < 3 and abs(p[1] - 310) < 3

    def test_no_block_none(self):
        assert perception.block_pixel(synth()) is None

    def test_tiny_blob_rejected(self):
        assert perception.block_pixel(synth((300, 305, 300, 305))) is None

    def test_top_rows_masked(self):
        assert perception.block_pixel(synth((0, 55, 200, 400))) is None

    def test_saucer_fraction_local(self):
        # block filling the saucer disk reads high; red elsewhere reads zero
        img = synth((285, 345, 434, 494))     # 60x60 red at saucer (464,315)
        assert perception.saucer_red_fraction(img, (464, 315), 30) > 0.9
        img2 = synth((100, 200, 100, 200))    # red far away (a hand)
        assert perception.saucer_red_fraction(img2, (464, 315), 30) == 0.0

    def test_invalid_frame_fails_closed(self):
        assert perception.block_pixel(None) is None
        assert perception.saucer_red_fraction(None, (464, 315), 30) == 0.0


class TestServoController:
    """Wrist-image servo: after the open-loop stage lands near the block,
    close the loop on WHERE THE BLOCK SITS IN THE WRIST FRAME vs the
    demonstrated pre-grasp target. Fixes what no table can: open-loop
    extrapolation into the held-out hole missed by cm in nine of nine
    shakedown-4 attempts while the block was visible in the wrist view
    every time. Best-effort by design: no block or no progress -> STOP
    and proceed, never abort (the guard covers real danger)."""

    def make(self, **kw):
        from b601.planner.io_support import ServoController
        cfg = dict(target=(360.0, 404.0), tolerance_px=25.0,
                   gain=0.5, max_step_deg=1.5, max_total_deg=12.0,
                   max_ticks=120, stall_ticks=30,
                   jx_pan=-12.8, jy_elbow=2.5)
        cfg.update(kw)
        return ServoController(**cfg)

    def _run_plant(self, servo, start, jac=(-12.8, 2.5)):
        """Linear plant: centroid moves per the true jacobian."""
        c = np.array(start, dtype=float)
        for _ in range(200):
            step = servo.step((c[0], c[1]))
            if step is None:
                return c, servo
            dpan, dreach = step
            c[0] += jac[0] * dpan
            c[1] += jac[1] * dreach
        raise AssertionError("servo never terminated")

    def test_converges_on_linear_plant(self):
        c, servo = self._run_plant(self.make(), (300.0, 350.0))
        assert servo.converged
        assert abs(c[0] - 360) <= 25 and abs(c[1] - 404) <= 25

    def test_steps_are_capped(self):
        servo = self.make()
        dpan, dreach = servo.step((100.0, 200.0))   # huge error
        assert abs(dpan) <= 1.5 and abs(dreach) <= 1.5

    def test_total_budget_capped(self):
        servo = self.make(max_total_deg=3.0)
        total = 0.0
        c = np.array([100.0, 404.0])
        for _ in range(200):
            step = servo.step((c[0], c[1]))
            if step is None:
                break
            total += abs(step[0])
            # adversarial plant: centroid never moves
        assert total <= 3.0 + 1e-9
        assert not servo.converged

    def test_no_block_stops_not_raises(self):
        servo = self.make()
        assert servo.step(None) is None
        assert not servo.converged

    def test_stall_detection_stops(self):
        servo = self.make(stall_ticks=10)
        for i in range(300):
            if servo.step((100.0, 404.0)) is None:   # frozen plant
                break
        assert i < 250
        assert not servo.converged
