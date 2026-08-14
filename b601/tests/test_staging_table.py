"""The staging table: block pixel in, pre-grasp joint pose out.

Built from the demonstration corpus — each episode pairs a block position
with the arm pose the operator staged just before grasping. The table
interpolates between demonstrated placements (k-nearest, inverse-distance)
and REFUSES to answer far outside demonstrated coverage: staging the arm at
a wild extrapolation is how a policy meets a table, and the held-out zone
sits 40-80 px from covered points — inside a modest guard, but the guard
must exist and must name its limit.
"""
import pytest

from b601.staging.table import StagingError, StagingTable


def square_table():
    # four demonstrated placements at the corners of a square, poses that
    # differ only in the first joint for easy arithmetic
    pts = [(100.0, 100.0), (200.0, 100.0), (100.0, 200.0), (200.0, 200.0)]
    poses = [[10.0, 1, 1, 1, 1, 1, 40], [20.0, 1, 1, 1, 1, 1, 40],
             [30.0, 1, 1, 1, 1, 1, 40], [40.0, 1, 1, 1, 1, 1, 40]]
    return StagingTable.fit(pts, poses)


def test_a_demonstrated_placement_returns_its_own_pose():
    t = square_table()
    pose, dist = t.query(100.0, 100.0)
    assert pose[0] == pytest.approx(10.0)
    assert dist == pytest.approx(0.0)


def test_a_query_between_placements_interpolates():
    t = square_table()
    pose, _ = t.query(150.0, 100.0)          # midway between 10 and 20
    assert 10.0 < pose[0] < 20.0


def test_the_nearest_distance_is_reported_for_the_caller_to_judge():
    t = square_table()
    _, dist = t.query(150.0, 100.0)
    assert dist == pytest.approx(50.0)


def test_a_query_far_outside_coverage_is_refused_not_guessed():
    """Staging at a wild extrapolation points the policy somewhere no
    demonstration ever went. The error must name the distance and limit."""
    t = square_table()
    with pytest.raises(StagingError, match="px"):
        t.query(500.0, 500.0)


def test_the_extrapolation_guard_is_configurable_and_bounds_the_held_out_gap():
    """The held-out zone sits 40-80 px from covered placements — a table with
    the default guard must answer there, measured, not by luck."""
    t = square_table()
    pose, dist = t.query(200.0, 270.0)       # 70 px below a corner
    assert dist == pytest.approx(70.0)
    assert pose[0] == pytest.approx(40.0, abs=15)


def test_too_few_placements_to_interpolate_is_refused():
    with pytest.raises(StagingError, match="at least"):
        StagingTable.fit([(1.0, 1.0)], [[1, 2, 3, 4, 5, 6, 7]])


def test_mismatched_points_and_poses_are_refused():
    with pytest.raises(StagingError, match="match"):
        StagingTable.fit([(1.0, 1.0), (2.0, 2.0)], [[1, 2, 3, 4, 5, 6, 7]])


def test_round_trip_through_json(tmp_path):
    """The table is a pinned artifact; what is loaded must be what was fit."""
    t = square_table()
    p = tmp_path / "staging.json"
    t.write(p)
    t2 = StagingTable.load(p)
    assert t2.query(150.0, 100.0)[0] == pytest.approx(t.query(150.0, 100.0)[0])
