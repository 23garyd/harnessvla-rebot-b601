"""FK cross-check diagnostic.

The comparison logic is tested unconditionally with stub solvers. The real
solvers are exercised only when placo and Pinocchio are installed and a URDF
is available — neither is a dependency of the unpowered suite, and the URDF
lives with the vendor sources on the robot PC, not in this repository.
"""
import pytest

from b601.bringup.kinematics_check import (ARM_JOINTS, KinematicsCheckError,
                                           compare_fk, model_root,
                                           render_report,
                                           sample_joint_vectors, staged_urdf)


def fk_at(offset):
    return lambda q: (0.1 + offset, 0.2, 0.3 + sum(q) * 1e-6)


# --- comparison logic -----------------------------------------------------

def test_identical_solvers_disagree_by_zero():
    worst = compare_fk(fk_at(0.0), fk_at(0.0), sample_joint_vectors(20))
    assert worst[0].position_m == 0.0


def test_disagreement_is_the_euclidean_distance_between_poses():
    worst = compare_fk(fk_at(0.0), fk_at(0.003), [(0.0,) * 6])
    assert worst[0].position_m == pytest.approx(0.003)


def test_worst_case_is_reported_first():
    """The maximum is the number that decides whether FK is usable; an
    average over mostly-agreeing samples would hide a single bad region."""
    calls = iter([(0.0, 0.0, 0.0), (0.0, 0.0, 0.5), (0.0, 0.0, 0.01)])
    worst = compare_fk(lambda q: (0.0, 0.0, 0.0), lambda q: next(calls),
                       [(0.0,) * 6] * 3)
    assert worst[0].position_m == pytest.approx(0.5)
    assert [round(d.position_m, 3) for d in worst] == [0.5, 0.01, 0.0]


# --- sampling -------------------------------------------------------------

def test_sampling_is_deterministic():
    """A disagreement has to be reproducible: 'it failed on some random pose'
    is not a bug report."""
    assert sample_joint_vectors(50) == sample_joint_vectors(50)


def test_sampling_starts_at_zero_then_sweeps_each_axis_alone():
    samples = sample_joint_vectors(20, span_deg=90.0)
    assert samples[0] == (0.0,) * len(ARM_JOINTS)
    single_axis = [s for s in samples[1:13] if sum(1 for v in s if v) == 1]
    assert len(single_axis) == 12, "each axis should move alone, both ways"


def test_sampling_respects_the_requested_count():
    assert len(sample_joint_vectors(7)) == 7
    assert len(sample_joint_vectors(300)) == 300


# --- mesh path handling ---------------------------------------------------

def test_model_root_finds_the_directory_holding_meshes(tmp_path):
    root = tmp_path / "desc"
    (root / "urdf").mkdir(parents=True)
    (root / "meshes").mkdir()
    urdf = root / "urdf" / "arm.urdf"
    urdf.write_text("<robot name='x'/>")
    assert model_root(urdf) == root


def test_urdf_is_staged_beside_its_meshes(tmp_path):
    """placo resolves mesh paths against the URDF FILE's directory; the vendor
    ships the URDF one level below the meshes, so loading it in place fails."""
    root = tmp_path / "desc"
    (root / "urdf").mkdir(parents=True)
    (root / "meshes").mkdir()
    (root / "meshes" / "base.STL").write_text("solid")
    urdf = root / "urdf" / "arm.urdf"
    urdf.write_text("<robot name='x'/>")
    with staged_urdf(urdf) as staged:
        assert (staged.parent / "meshes" / "base.STL").exists()
        assert staged.read_text() == "<robot name='x'/>"


def test_a_urdf_already_beside_its_meshes_is_used_in_place(tmp_path):
    (tmp_path / "meshes").mkdir()
    urdf = tmp_path / "arm.urdf"
    urdf.write_text("<robot name='x'/>")
    with staged_urdf(urdf) as staged:
        assert staged == urdf


# --- reporting ------------------------------------------------------------

def test_report_says_agreement_does_not_mean_correctness():
    worst = compare_fk(fk_at(0.0), fk_at(0.0), [(0.0,) * 6])
    out = render_report(worst, tolerance_m=1e-6)
    assert "identical wrong answers" in out
    assert "Day-3 calibration" in out


def test_report_names_the_worst_joint_vector_on_failure():
    worst = compare_fk(fk_at(0.0), fk_at(0.05), [(1.0,) * 6])
    out = render_report(worst, tolerance_m=1e-6)
    assert "WORST CASE" in out
    assert "do not treat eef_pose() as usable" in out.lower()


# --- real solvers (skipped unless the environment has them) ---------------

def test_the_two_solvers_agree_on_the_real_urdf():
    """Runs only where the vendor URDF and both solvers are present — set
    B601_URDF. On the robot PC this is the check that must pass before
    eef_pose() is trusted by anything."""
    import os

    from b601.bringup.kinematics_check import pinocchio_fk, placo_fk
    urdf = os.environ.get("B601_URDF")
    if not urdf:
        pytest.skip("set B601_URDF to the vendor URDF to run this")
    try:
        fk_a, fk_b = placo_fk(urdf), pinocchio_fk(urdf)
    except KinematicsCheckError as exc:
        pytest.skip(str(exc))
    worst = compare_fk(fk_a, fk_b, sample_joint_vectors(50))
    assert worst[0].position_m < 1e-6, render_report(worst, 1e-6)


def test_missing_solver_raises_a_named_error_not_an_import_error():
    from b601.bringup.kinematics_check import _require
    with pytest.raises(KinematicsCheckError, match="not importable"):
        _require("no_such_kinematics_library", "pip install nothing")
