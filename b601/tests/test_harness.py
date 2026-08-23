"""The harness loop: look -> stage -> invoke frozen policy -> lift ->
verify -> branch (success / place-recover / re-ground) -> retry <= N ->
graceful give-up. Pure state machine over injected hardware callables, so
every branch is testable unpowered.

Fail-closed rules under test:
- no block found and saucer empty: give up, go home — never guess a pose
- staging refusal (outside demonstrated coverage): refuse, go home
- any hardware exception: abort with NO further motion commands (a stalled
  or faulted arm must not be commanded home blindly)
- still holding after the place recovery: give up (block stuck — a human
  problem), do not thrash
- verification happens only AFTER lift_to_verify (measured blind spot:
  low hover beside an un-grasped block fools both cues)
"""
import pytest

from b601.planner.grasp_verifier import GraspVerdict
from b601.planner.harness import Harness, TrialResult
from b601.staging.table import StagingTable, StagingError


def make_table():
    # 4 corners + centre so interior queries interpolate
    pts = [(100, 100), (500, 100), (100, 400), (500, 400), (300, 250)]
    poses = [[float(i)] * 7 for i in range(5)]
    return StagingTable.fit(pts, poses, k=3, max_extrapolation_px=100)


HELD = GraspVerdict(True, 0.3, 0.4, True, "held")
EMPTY = GraspVerdict(False, 0.0, 0.0, False, "red below threshold")


class FakeIO:
    """Scriptable hardware: each field is a list consumed left to right
    (last value repeats). Every call is appended to .log."""

    def __init__(self, perceive=((300.0, 250.0),), saucer=(False,),
                 verify=(EMPTY,), fail_on=None):
        self._perceive = list(perceive)
        self._saucer = list(saucer)
        self._verify = list(verify)
        self._fail_on = fail_on
        self.log = []

    def _next(self, seq):
        return seq.pop(0) if len(seq) > 1 else seq[0]

    def _call(self, name):
        self.log.append(name)
        if self._fail_on == name:
            raise RuntimeError(f"hardware fault in {name}")

    def perceive_block(self):
        self._call("perceive_block")
        return self._next(self._perceive)

    def block_in_saucer(self):
        self._call("block_in_saucer")
        return self._next(self._saucer)

    def stage(self, pose):
        self._call("stage")

    def invoke_policy(self):
        self._call("invoke_policy")

    def lift_to_verify(self):
        self._call("lift_to_verify")

    def verify_frame(self):
        self._call("verify_frame")
        return self._next(self._verify)

    def place_recover(self):
        self._call("place_recover")

    def go_home(self):
        self._call("go_home")


def run(io, **kw):
    return Harness(make_table(), io, **kw).run_trial()


class TestHappyPaths:
    def test_policy_places_first_try(self):
        io = FakeIO(saucer=[True], verify=[EMPTY])
        r = run(io)
        assert r.outcome == "success"
        assert len(r.attempts) == 1
        assert io.log.count("invoke_policy") == 1
        assert "go_home" in io.log

    def test_grasped_but_not_placed_triggers_place_recovery(self):
        # verify burst says held; after place_recover gripper empty, saucer yes
        io = FakeIO(saucer=[False, True],
                    verify=[HELD, HELD, HELD, EMPTY])
        r = run(io, verify_burst=3, verify_majority=2)
        assert r.outcome == "success"
        assert "place_recover" in io.log

    def test_grasp_failure_regrounds_and_retries(self):
        io = FakeIO(perceive=[(300.0, 250.0), (310.0, 240.0)],
                    saucer=[False, True], verify=[EMPTY])
        r = run(io)
        assert r.outcome == "success"
        assert len(r.attempts) == 2
        assert io.log.count("perceive_block") == 2   # re-grounded, not cached

    def test_block_already_in_saucer_when_not_visible(self):
        io = FakeIO(perceive=[None], saucer=[True])
        r = run(io)
        assert r.outcome == "success"
        assert io.log.count("invoke_policy") == 0


class TestGiveUps:
    def test_gives_up_after_max_attempts(self):
        io = FakeIO(saucer=[False], verify=[EMPTY])
        r = run(io, max_attempts=3)
        assert r.outcome == "gave_up"
        assert len(r.attempts) == 3
        assert io.log.count("invoke_policy") == 3
        assert io.log[-1] == "go_home"

    def test_no_block_and_empty_saucer_gives_up_without_motion(self):
        io = FakeIO(perceive=[None], saucer=[False])
        r = run(io)
        assert r.outcome == "gave_up"
        assert "not found" in r.detail
        assert io.log.count("invoke_policy") == 0
        assert "stage" not in io.log

    def test_staging_refusal_is_refused_not_a_guess(self):
        io = FakeIO(perceive=[(50.0, 900.0)])   # far outside coverage
        r = run(io)
        assert r.outcome == "refused"
        assert "stage" not in io.log
        assert io.log[-1] == "go_home"

    def test_still_held_after_place_recovery_gives_up_stuck(self):
        io = FakeIO(saucer=[False], verify=[HELD])
        r = run(io)
        assert r.outcome == "gave_up"
        assert "stuck" in r.detail
        assert io.log.count("place_recover") == 1   # no thrashing

class TestFailClosed:
    def test_hardware_fault_aborts_with_no_further_motion(self):
        io = FakeIO(fail_on="invoke_policy")
        r = run(io)
        assert r.outcome == "error_abort"
        assert "invoke_policy" in r.detail
        # nothing after the fault — not even go_home
        assert io.log[-1] == "invoke_policy"

    def test_verify_only_after_lift(self):
        io = FakeIO(saucer=[False], verify=[EMPTY])
        run(io)
        for i, call in enumerate(io.log):
            if call == "verify_frame":
                assert "lift_to_verify" in io.log[:i]

    def test_burst_minority_held_is_not_held(self):
        # 2 of 5 held -> not held -> re-ground path, no place_recover
        io = FakeIO(saucer=[False],
                    verify=[HELD, HELD, EMPTY, EMPTY, EMPTY])
        run(io, max_attempts=1, verify_burst=5, verify_majority=3)
        assert "place_recover" not in io.log


class TestDeepRetry:
    def test_retries_stage_from_deep_table(self):
        # attempt 1 uses the normal table; attempts 2+ stage DEEPER (at-closure
        # poses) — a near-miss retry should leave the policy no room to drift
        deep = StagingTable.fit(
            [(100, 100), (500, 100), (100, 400), (500, 400), (300, 250)],
            [[float(i) + 100.0] * 7 for i in range(5)])
        staged = []

        class IO(FakeIO):
            def stage(self, pose):
                staged.append(list(pose))
                super().stage(pose)

        io = IO(saucer=[False], verify=[EMPTY])
        r = Harness(make_table(), io, deep_table=deep,
                    max_attempts=2).run_trial()
        assert r.outcome == "gave_up"
        assert len(staged) == 2
        assert staged[0][0] < 100.0 <= staged[1][0]   # deep poses offset +100

    def test_no_deep_table_keeps_normal_staging(self):
        staged = []

        class IO(FakeIO):
            def stage(self, pose):
                staged.append(list(pose))
                super().stage(pose)

        io = IO(saucer=[False], verify=[EMPTY])
        Harness(make_table(), io, max_attempts=2).run_trial()
        assert len(staged) == 2
        assert staged[0] == staged[1]   # same pixel, same table, same pose


class TestRecords:
    def test_attempt_records_carry_pixel_and_reason(self):
        io = FakeIO(saucer=[False], verify=[EMPTY])
        r = run(io, max_attempts=2)
        assert isinstance(r, TrialResult)
        for a in r.attempts:
            assert a.pixel == (300.0, 250.0)
            assert a.staging_distance_px >= 0.0
            assert a.reason
