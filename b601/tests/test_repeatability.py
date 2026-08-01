"""Day-2 repeatability harness.

The plan's Day-2 gate is twenty consecutive low-speed motions with no fault,
collision, or manual correction, evidenced by a log of commanded vs achieved
state, error, duration and faults. This is the harness that produces it —
written and tested unpowered so that on bring-up day the only new variable is
the arm.

Two things it deliberately refuses to do:

  - Guess at what it cannot observe. Collisions and manual corrections are
    human observations. The gate function requires an explicit operator
    attestation and will not pass without one, so "the software said the gate
    passed" can never stand in for someone watching the robot.
  - Continue after a fault. SafeDriver latches, so every subsequent motion
    would be refused anyway; the run stops at the fault and reports how many
    consecutive clean motions it achieved. A gate that counts twenty motions
    across a fault is not measuring what it says.
"""
import csv

import pytest

from b601.bringup.repeatability import (DEFAULT_POSES, RepeatabilityRun,
                                        error_histogram, gate_status,
                                        run_repeatability, write_csv)
from b601.driver.base import SafeDriver
from b601.driver.mock import MockDriver
from b601.safety.limits import HomeContract, MotionLimits, Workspace

WS = Workspace(x_min=0.15, x_max=0.55, y_min=-0.30, y_max=0.30,
               z_min=0.02, z_max=0.50)
LIM = MotionLimits(max_joint_velocity=1.0, max_cartesian_speed=0.25,
                   max_step_distance=0.15, max_gripper_force=1.0)
HOME = HomeContract(xyz=(0.30, 0.00, 0.35), tolerance_m=0.02)

# Close together on purpose: max_step_distance is 0.15 m, and the harness must
# exercise repeatability, not the step guard.
POSES = [(0.30, 0.00, 0.35), (0.34, 0.04, 0.33), (0.28, -0.04, 0.37),
         (0.33, -0.02, 0.31), (0.31, 0.03, 0.39)]


class OffsetMock(MockDriver):
    """Achieves a pose offset from the command — a real arm's tracking error."""

    def __init__(self, offset=(0.0, 0.0, 0.0), **kw):
        super().__init__(**kw)
        self.offset = offset

    def move_to(self, xyz, speed):
        super().move_to(xyz, speed)
        self._pose = tuple(a + b for a, b in zip(xyz, self.offset))


def driver(cls=MockDriver, **kw):
    d = cls(**kw)
    return d, SafeDriver(d, WS, LIM, HOME)


# --- the run --------------------------------------------------------------

def test_five_poses_four_cycles_is_twenty_motions():
    _, sd = driver()
    run = run_repeatability(sd, POSES, cycles=4)
    assert len(run.trials) == 20
    assert sd.motions == 20


def test_every_trial_records_command_achieved_error_and_duration():
    _, sd = driver(OffsetMock, offset=(0.001, 0.0, 0.0))
    run = run_repeatability(sd, POSES, cycles=1)
    t = run.trials[0]
    assert t.commanded == POSES[0]
    assert t.achieved == pytest.approx((POSES[0][0] + 0.001,) + POSES[0][1:])
    assert t.error_m == pytest.approx(0.001)
    assert t.duration_s >= 0.0
    assert t.fault is None


def test_error_is_euclidean_over_all_three_axes():
    _, sd = driver(OffsetMock, offset=(0.003, 0.004, 0.0))
    run = run_repeatability(sd, POSES, cycles=1)
    assert run.trials[0].error_m == pytest.approx(0.005)


def test_cycles_are_recorded_so_drift_over_time_is_visible():
    """A pose that degrades on later cycles is the signal to look for; an
    aggregate mean would hide it."""
    _, sd = driver()
    run = run_repeatability(sd, POSES, cycles=3)
    assert [t.cycle for t in run.trials[:5]] == [1, 1, 1, 1, 1]
    assert sorted({t.cycle for t in run.trials}) == [1, 2, 3]


# --- faults stop the run --------------------------------------------------

def test_a_hardware_fault_stops_the_run_and_is_recorded():
    mock, sd = driver()
    mock.fault_on_next_move = "joint 3 overcurrent"
    run = run_repeatability(sd, POSES, cycles=4)
    assert len(run.trials) == 1
    assert "overcurrent" in run.trials[0].fault
    assert run.consecutive_ok == 0


def test_consecutive_ok_counts_only_up_to_the_fault():
    mock, sd = driver()
    run = run_repeatability(sd, POSES, cycles=1, before_move=lambda i: (
        setattr(mock, "fault_on_next_move", "CAN timeout") if i == 3 else None))
    assert run.consecutive_ok == 3
    assert run.trials[-1].fault is not None


def test_a_safety_violation_is_recorded_as_a_fault_not_raised():
    """The harness is evidence collection: it records the refusal and stops,
    rather than dying with a traceback halfway through a log."""
    _, sd = driver()
    run = run_repeatability(sd, [(0.95, 0.0, 0.35)], cycles=1)
    assert run.trials[0].fault is not None
    assert "workspace" in run.trials[0].fault


# --- the gate -------------------------------------------------------------

def test_gate_needs_twenty_consecutive_clean_motions():
    _, sd = driver()
    run = run_repeatability(sd, POSES, cycles=4)
    status = gate_status(run, operator_confirmed=True)
    assert status.passed is True


def test_gate_fails_below_twenty():
    _, sd = driver()
    run = run_repeatability(sd, POSES, cycles=3)
    status = gate_status(run, operator_confirmed=True)
    assert status.passed is False
    assert "15" in status.reason


def test_gate_cannot_pass_without_an_operator_attestation():
    """Collisions and manual corrections are not observable from here. The
    software half of the gate is not the gate."""
    _, sd = driver()
    run = run_repeatability(sd, POSES, cycles=4)
    status = gate_status(run, operator_confirmed=False)
    assert status.passed is False
    assert "operator" in status.reason.lower()


def test_gate_fails_when_a_fault_interrupted_the_run():
    mock, sd = driver()
    run = run_repeatability(sd, POSES, cycles=4, before_move=lambda i: (
        setattr(mock, "fault_on_next_move", "CAN timeout") if i == 10 else None))
    assert gate_status(run, operator_confirmed=True).passed is False


# --- evidence -------------------------------------------------------------

def test_csv_has_one_row_per_trial_with_the_plan_s_columns(tmp_path):
    _, sd = driver(OffsetMock, offset=(0.002, 0.0, 0.0))
    run = run_repeatability(sd, POSES, cycles=2)
    out = tmp_path / "repeatability.csv"
    write_csv(run, out)
    rows = list(csv.DictReader(out.open()))
    assert len(rows) == 10
    for column in ("pose_id", "cycle", "cmd_x", "achieved_x", "error_m",
                   "duration_s", "speed", "fault"):
        assert column in rows[0]
    assert float(rows[0]["error_m"]) == pytest.approx(0.002)


def test_summary_reports_per_pose_max_error():
    """Per-pose, because one bad pose is the finding; a global mean buries it."""
    _, sd = driver(OffsetMock, offset=(0.002, 0.0, 0.0))
    run = run_repeatability(sd, POSES, cycles=2)
    summary = run.summary()
    assert set(summary) == {i for i in range(1, 6)}
    assert summary[1]["max_error_m"] == pytest.approx(0.002)
    assert summary[1]["n"] == 2


def test_histogram_bins_the_error_distribution():
    errors = [0.000, 0.001, 0.001, 0.004]
    bins = error_histogram(errors, bins=2)
    assert sum(count for _, _, count in bins) == 4
    assert bins[0][2] == 3


def test_histogram_of_an_empty_run_is_empty_not_a_crash():
    assert error_histogram([], bins=4) == []


def test_default_poses_are_inside_the_shipped_workspace():
    """They are conservative by construction — the plan asks for five
    conservative poses, and a pose the envelope rejects is not a test."""
    from b601.safety.config import load_limits
    workspace, _ = load_limits()
    assert len(DEFAULT_POSES) == 5
    for pose in DEFAULT_POSES:
        assert workspace.contains(pose)


def test_run_is_reported_as_incomplete_when_it_stopped_early():
    mock, sd = driver()
    mock.fault_on_next_move = "CAN timeout"
    run = run_repeatability(sd, POSES, cycles=4)
    assert isinstance(run, RepeatabilityRun)
    assert run.completed is False
