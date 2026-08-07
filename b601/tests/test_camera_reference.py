"""Detecting that a camera mount moved, without a metric calibration.

Sim finding 3 is the reason this exists. A stale reference coordinate produced
release errors of +0.078-0.082 m and inverted the strongest cell in the matrix,
and grep-based audits could not see it because the bad number never entered an
action — it biased estimator SELECTION. The physical analogue is a nudged camera
mount, and it is equally silent: every episode after the nudge carries a
systematic perception bias that is indistinguishable from policy error at
evaluation time.

A full camera-to-robot calibration would catch it. So does something far
cheaper: fixed landmarks in view, their pixel positions recorded once, and
compared at the start of every session. That is what this module does, and it is
what `calibration_report.md` means by "evidence that landmarks are stable across
a restart".

WHY LANDMARKS RATHER THAN THE WHOLE IMAGE. Comparing frames wholesale — pixel
difference, or feature matching over the scene — would flag drift every time an
object moved, and objects move in every single episode because moving them is
the task. Markers fixed at the workspace periphery are immune to that, and to
lighting, which auto-exposure-off does not fully control.

The comparison is PURE: landmark positions in, report out. No cameras, no
OpenCV, no filesystem. Detection is a thin adapter around cv2.aruco, the same
split the capture backends use.
"""
import pytest

from b601.cameras.reference import (DriftError, ReferenceSet, compare_landmarks,
                                    load_reference)


def ref(**kw):
    """Four landmarks at the corners of a notional workspace."""
    base = {0: (100.0, 100.0), 1: (500.0, 100.0),
            2: (500.0, 380.0), 3: (100.0, 380.0)}
    base.update(kw)
    return base


def shifted(landmarks, dx, dy):
    return {i: (x + dx, y + dy) for i, (x, y) in landmarks.items()}


# --- the mount has not moved ----------------------------------------------

def test_identical_landmarks_report_zero_drift():
    r = compare_landmarks("agentview", ref(), ref(), tolerance_px=3.0)
    assert r.median_displacement_px == 0.0
    assert r.max_displacement_px == 0.0
    assert r.passed


def test_sub_tolerance_detection_noise_passes():
    """Corner detection is not exact to the pixel. A fraction of a pixel of
    scatter is the detector, not the mount."""
    noisy = {0: (100.3, 99.8), 1: (499.7, 100.2),
             2: (500.2, 380.3), 3: (99.9, 379.8)}
    r = compare_landmarks("agentview", ref(), noisy, tolerance_px=3.0)
    assert r.max_displacement_px < 1.0
    assert r.passed


# --- the mount HAS moved ---------------------------------------------------

def test_a_uniform_shift_is_detected_and_measured():
    """THE CASE THIS EXISTS FOR. Every landmark moving together is a mount that
    moved, not a scene that changed."""
    r = compare_landmarks("agentview", ref(), shifted(ref(), 12.0, -5.0),
                          tolerance_px=3.0)
    assert r.median_displacement_px == pytest.approx(13.0, abs=0.01)
    assert not r.passed
    assert "drift" in r.summary()


def test_the_report_names_the_camera():
    r = compare_landmarks("agentview", ref(), shifted(ref(), 12.0, 0.0),
                          tolerance_px=3.0)
    assert "agentview" in r.summary()


def test_a_shift_just_under_tolerance_passes_and_just_over_fails():
    assert compare_landmarks("c", ref(), shifted(ref(), 2.9, 0), 3.0).passed
    assert not compare_landmarks("c", ref(), shifted(ref(), 3.1, 0), 3.0).passed


def test_tolerance_is_required_not_defaulted():
    """A drift tolerance is a per-installation number — it depends on lens,
    resolution and how far the landmarks sit. A default would be a number
    nobody chose, applied to a check people trust."""
    with pytest.raises(TypeError):
        compare_landmarks("agentview", ref(), ref())


# --- robustness of the statistic -------------------------------------------

def test_one_bumped_landmark_does_not_by_itself_fail_the_mount_check():
    """Deliberate. The median answers "did the MOUNT move", and one marker
    knocked askew is not that. It is still reported through
    max_displacement_px, so it cannot pass unseen."""
    current = ref()
    current[2] = (540.0, 380.0)                      # one marker moved 40 px
    r = compare_landmarks("agentview", ref(), current, tolerance_px=3.0)
    assert r.median_displacement_px < 3.0
    assert r.max_displacement_px == pytest.approx(40.0)
    assert r.passed
    assert "40.0" in r.summary()                     # visible even though it passed


def test_a_missing_landmark_fails_rather_than_being_skipped():
    """A landmark that cannot be seen has not been verified. Dropping it from
    the median would let a check pass on the markers that happen to be left."""
    current = ref()
    del current[1]
    r = compare_landmarks("agentview", ref(), current, tolerance_px=3.0)
    assert not r.passed
    assert r.missing == (1,)
    assert "missing" in r.summary()


def test_an_unexpected_extra_landmark_is_reported_but_does_not_fail():
    """An extra marker in view does not move the ones being checked."""
    current = ref()
    current[9] = (300.0, 240.0)
    r = compare_landmarks("agentview", ref(), current, tolerance_px=3.0)
    assert r.extra == (9,)
    assert r.passed
    assert "extra" in r.summary()


def test_no_reference_landmarks_at_all_raises():
    """Comparing against nothing would pass forever while checking nothing —
    the same structural blindness the pin probes were fixed for."""
    with pytest.raises(DriftError, match="no landmarks"):
        compare_landmarks("agentview", {}, ref(), tolerance_px=3.0)


def test_no_landmarks_detected_now_fails_loudly():
    """A camera showing nothing is the loudest possible failure and must not
    read as "no drift detected"."""
    r = compare_landmarks("agentview", ref(), {}, tolerance_px=3.0)
    assert not r.passed
    assert set(r.missing) == {0, 1, 2, 3}


# --- the stored artifact ---------------------------------------------------

def test_reference_round_trips_through_the_artifact(tmp_path):
    path = tmp_path / "calibration.json"
    ReferenceSet(method="landmark_drift_reference", dictionary="DICT_4X4_50",
                 tolerance_px=3.0,
                 cameras={"agentview": ref()}).write(path)
    loaded = load_reference(path)
    assert loaded.cameras["agentview"] == ref()
    assert loaded.tolerance_px == 3.0
    assert loaded.dictionary == "DICT_4X4_50"


def test_a_missing_artifact_raises_rather_than_defaulting(tmp_path):
    with pytest.raises(DriftError, match="not found"):
        load_reference(tmp_path / "nope.json")


def test_malformed_artifact_raises(tmp_path):
    path = tmp_path / "calibration.json"
    path.write_text("{not json")
    with pytest.raises(DriftError, match="not valid JSON"):
        load_reference(path)


def test_an_artifact_with_no_cameras_raises(tmp_path):
    path = tmp_path / "calibration.json"
    ReferenceSet("landmark_drift_reference", "DICT_4X4_50", 3.0, {}).write(path)
    with pytest.raises(DriftError, match="no cameras"):
        load_reference(path)


def test_a_camera_with_no_reference_is_not_silently_skipped(tmp_path):
    """`eye_in_hand` has no reference yet, because a wrist camera's landmarks
    only mean anything at a fixed arm pose. That must read as UNCHECKED, never
    as checked-and-clean."""
    from b601.cameras.reference import check_all
    path = tmp_path / "calibration.json"
    ReferenceSet("landmark_drift_reference", "DICT_4X4_50", 3.0,
                 {"agentview": ref()}).write(path)
    reference = load_reference(path)
    reports, unchecked = check_all(reference,
                                   {"agentview": ref(), "eye_in_hand": ref()})
    assert [r.name for r in reports] == ["agentview"]
    assert unchecked == ("eye_in_hand",)


def test_a_referenced_camera_that_produced_no_frame_is_a_failure(tmp_path):
    """Different from having no reference: this one WAS supposed to be checked."""
    from b601.cameras.reference import check_all
    path = tmp_path / "calibration.json"
    ReferenceSet("landmark_drift_reference", "DICT_4X4_50", 3.0,
                 {"agentview": ref()}).write(path)
    with pytest.raises(DriftError, match="agentview"):
        check_all(load_reference(path), {})


# --- the command the operator runs ----------------------------------------

def fake_grab(landmarks):
    """The 'frame' is the landmark dict itself; fake_detect just hands it back.
    Keeps the CLI's bookkeeping testable with no OpenCV and no cameras."""
    def grab(cameras, burst=1):
        out = {}
        for c in cameras:
            marks = landmarks.get(c.name, {})
            out[c.name] = [dict(marks)] * burst if burst > 1 else marks
        return out
    return grab


def fake_detect(frame, dictionary=None):
    return dict(frame or {})


def test_record_writes_an_artifact_that_loads_back(tmp_path, capsys):
    from b601.cameras.reference import main
    path = tmp_path / "calibration.json"
    rc = main(["--record"], detect=fake_detect, grab=fake_grab({"agentview": ref()}), path=path)
    assert rc == 0
    assert load_reference(path).cameras["agentview"] == ref()
    assert "agentview" in capsys.readouterr().out


def test_record_refuses_when_no_camera_produced_a_frame(tmp_path, capsys):
    """Recording from nothing would create a check that passes forever while
    verifying nothing.

    NOTE the premise changed 2026-08-06: an absence of ArUco markers is no
    longer a refusal, because the ORB fallback records the scene's own texture
    instead. What is still a refusal is having no FRAME at all — and, on the
    ORB path, a scene too featureless to match, which `_record` checks by
    trying to estimate a homography before it writes anything. That branch
    needs OpenCV and is verified against hardware rather than here."""
    from b601.cameras.reference import main
    path = tmp_path / "calibration.json"
    rc = main(["--record"], detect=fake_detect,
              grab=lambda cameras, burst=1: {c.name: None for c in cameras}, path=path)
    assert rc == 1
    assert not path.exists()
    assert "nothing to record" in capsys.readouterr().err


def test_record_succeeds_when_only_some_cameras_have_landmarks(tmp_path, capsys):
    """The wrist camera legitimately has none — its landmarks would move with
    it. Refusing to record at all because of that would make the fixed
    camera's mount unguarded too. It is reported, not skipped silently."""
    from b601.cameras.reference import main
    path = tmp_path / "calibration.json"
    rc = main(["--record"],
              detect=fake_detect, grab=fake_grab({"agentview": ref(), "eye_in_hand": {}}),
              path=path)
    assert rc == 0
    assert set(load_reference(path).cameras) == {"agentview"}
    assert "NOT REFERENCED" in capsys.readouterr().out


def test_check_passes_when_nothing_moved(tmp_path, capsys):
    from b601.cameras.reference import main
    path = tmp_path / "calibration.json"
    main(["--record"], detect=fake_detect, grab=fake_grab({"agentview": ref()}), path=path)
    assert main([], detect=fake_detect, grab=fake_grab({"agentview": ref()}), path=path) == 0
    assert "DRIFT OK" in capsys.readouterr().out


def test_check_fails_when_the_mount_moved(tmp_path, capsys):
    from b601.cameras.reference import main
    path = tmp_path / "calibration.json"
    main(["--record"], detect=fake_detect, grab=fake_grab({"agentview": ref()}), path=path)
    rc = main([], detect=fake_detect, grab=fake_grab({"agentview": shifted(ref(), 20, 0)}),
              path=path)
    assert rc == 1
    assert "DRIFT DETECTED" in capsys.readouterr().out


def test_check_without_a_reference_fails_with_guidance(tmp_path, capsys):
    from b601.cameras.reference import main
    rc = main([], detect=fake_detect, grab=fake_grab({"agentview": ref()}),
              path=tmp_path / "nope.json")
    assert rc == 1
    assert "--record" in capsys.readouterr().err


def test_check_names_cameras_it_could_not_verify(tmp_path, capsys):
    """`eye_in_hand` has no stored reference. The operator must see that it was
    NOT checked, or absence of a failure reads as evidence of no drift."""
    from b601.cameras.reference import main
    path = tmp_path / "calibration.json"
    main(["--record"], detect=fake_detect, grab=fake_grab({"agentview": ref()}), path=path)
    main([], detect=fake_detect, grab=fake_grab({"agentview": ref(), "eye_in_hand": ref()}),
         path=path)
    assert "NOT CHECKED" in capsys.readouterr().out


def test_unknown_argument_is_rejected(tmp_path):
    from b601.cameras.reference import main
    assert main(["--force"], detect=fake_detect, grab=fake_grab({}), path=tmp_path / "c.json") == 64


# --- marker-free drift: homography over natural scene features ------------
#
# Measured on this workspace 2026-08-06: 1512 ORB features in the periphery,
# 609 of them strong. So markers are not required HERE — the scene carries
# enough texture on its own. The homography is applied to a fixed grid of probe
# points, and the displacement of those points is the drift, which means the
# verdict runs through exactly the same compare_landmarks as the ArUco path.

IDENTITY = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))


def grid():
    from b601.cameras.reference import probe_grid
    return probe_grid(640, 480)


def test_a_probe_grid_is_deterministic_and_inside_the_frame():
    g = grid()
    assert g == grid()
    assert len(g) >= 4
    assert all(0 <= x < 640 and 0 <= y < 480 for x, y in g.values())


def test_an_identity_homography_moves_nothing():
    from b601.cameras.reference import homography_landmarks
    assert homography_landmarks(grid(), IDENTITY) == grid()


def test_a_translation_homography_moves_every_point_equally():
    """A camera nudged sideways translates the whole scene. That is the signal
    the median displacement is built to catch."""
    from b601.cameras.reference import homography_landmarks
    H = ((1.0, 0.0, 12.0), (0.0, 1.0, -5.0), (0.0, 0.0, 1.0))
    moved = homography_landmarks(grid(), H)
    for i, (x, y) in grid().items():
        assert moved[i] == pytest.approx((x + 12.0, y - 5.0))
    r = compare_landmarks("agentview", grid(), moved, tolerance_px=3.0)
    assert r.median_displacement_px == pytest.approx(13.0, abs=0.01)
    assert not r.passed


def test_a_rotation_displaces_points_by_different_amounts():
    """A rotated mount is not a uniform shift: points far from the centre of
    rotation move further. The check must still fire."""
    import math
    from b601.cameras.reference import homography_landmarks
    a = math.radians(2.0)
    H = ((math.cos(a), -math.sin(a), 0.0),
         (math.sin(a), math.cos(a), 0.0), (0.0, 0.0, 1.0))
    moved = homography_landmarks(grid(), H)
    d = {i: math.dist(grid()[i], moved[i]) for i in grid()}
    assert max(d.values()) > min(d.values()) + 1.0
    assert not compare_landmarks("c", grid(), moved, tolerance_px=3.0).passed


def test_perspective_division_is_applied():
    """The third row is not decorative — ignoring it would under-report drift
    on a camera that tilted rather than slid."""
    from b601.cameras.reference import homography_landmarks
    H = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.001, 0.0, 1.0))
    moved = homography_landmarks({0: (100.0, 200.0)}, H)
    assert moved[0] == pytest.approx((100.0 / 1.1, 200.0 / 1.1))


def test_a_homography_that_could_not_be_estimated_raises():
    """cv2 returns None when it cannot find one. Treating that as "no drift"
    would be a check that passes precisely when it failed."""
    from b601.cameras.reference import homography_landmarks
    with pytest.raises(DriftError, match="homography"):
        homography_landmarks(grid(), None)


def test_a_degenerate_homography_raises():
    from b601.cameras.reference import homography_landmarks
    with pytest.raises(DriftError, match="homography"):
        homography_landmarks(grid(), ((0.0,) * 3,) * 3)


def test_only_fixed_mounts_are_given_a_drift_reference(tmp_path, capsys):
    """A wrist camera's view changes with every arm pose, so a reference for it
    would measure the arm, not the mount, and would fail constantly for the
    wrong reason. The module docstring said this from the start; the marker-free
    path recorded one anyway until this test existed.

    Excluded explicitly and reported, never silently: NOT CHECKED must remain
    distinguishable from checked-and-clean."""
    from b601.cameras.reference import main
    path = tmp_path / "calibration.json"
    rc = main(["--record"], detect=fake_detect,
              grab=fake_grab({"agentview": ref(), "eye_in_hand": ref()}),
              path=path)
    assert rc == 0
    assert set(load_reference(path).cameras) == {"agentview"}
    out = capsys.readouterr().out
    assert "eye_in_hand" in out and "wrist" in out.lower()


def test_a_camera_without_an_orb_reference_still_appears_as_unchecked(tmp_path):
    """It must not simply vanish from the report. Absent reads as 'everything
    was checked'; NOT CHECKED reads as what it is."""
    from b601.cameras.reference import ORB_METHOD, current_landmarks
    path = tmp_path / "calibration.json"
    ReferenceSet(ORB_METHOD, "", 3.0, {"agentview": ref()},
                 images={}).write(path)
    reference = load_reference(path)
    detected = current_landmarks(reference, {"eye_in_hand": {}}, path,
                                 detect=fake_detect)
    assert "eye_in_hand" in detected


# --- phantom rejection: a landmark must prove it is real ------------------
#
# MEASURED, repeatedly, on this workspace: the cutting mat's grid makes ArUco
# hallucinate. Across three separate 15-frame captures it produced ids 17, 22,
# 10, 34, 37, 38 -- each seen ONCE, 6-18 px, at scattered positions, and id 190
# once appeared in 10 of 12 frames with 108 px of jitter. Recording any of them
# as a landmark would bake in something that vanishes on the next run and fails
# the check forever after, for no real reason.
#
# The rule is agreement across frames, not plausibility in one.

def frames_of(*per_frame):
    return list(per_frame)


def test_a_landmark_seen_in_every_frame_at_one_place_is_accepted():
    from b601.cameras.reference import stable_landmarks
    seq = frames_of({0: (100.0, 100.0)}, {0: (100.2, 99.9)}, {0: (99.9, 100.1)},
                    {0: (100.1, 100.0)}, {0: (99.8, 100.0)})
    out = stable_landmarks(seq)
    assert set(out) == {0}
    assert out[0] == pytest.approx((100.0, 100.0), abs=0.2)     # the mean


def test_a_landmark_missing_from_any_frame_is_rejected():
    """The real phantoms were each seen exactly once."""
    from b601.cameras.reference import stable_landmarks
    seq = frames_of({0: (100.0, 100.0), 9: (300.0, 200.0)},
                    *[{0: (100.0, 100.0)}] * 5)
    assert set(stable_landmarks(seq)) == {0}


def test_a_landmark_that_jumps_around_is_rejected():
    """id 190 was seen in 10 of 12 frames with 108 px of jitter — present often
    enough to look real, in a different place every time."""
    from b601.cameras.reference import stable_landmarks
    seq = frames_of({7: (100.0, 100.0)}, {7: (250.0, 180.0)}, {7: (400.0, 60.0)},
                    {7: (150.0, 300.0)}, {7: (320.0, 120.0)})
    assert stable_landmarks(seq) == {}


def test_the_jitter_bound_is_configurable():
    from b601.cameras.reference import stable_landmarks
    seq = frames_of(*[{0: (100.0, 100.0)}] * 4, {0: (103.0, 100.0)})
    assert stable_landmarks(seq, max_jitter_px=5.0) != {}
    assert stable_landmarks(seq, max_jitter_px=0.5) == {}


def test_too_few_frames_to_establish_stability_raises():
    """One frame cannot distinguish a marker from a phantom — every phantom
    this workspace produced looked perfect in the frame it appeared in."""
    from b601.cameras.reference import stable_landmarks
    with pytest.raises(DriftError, match="at least"):
        stable_landmarks(frames_of({0: (1.0, 1.0)}))


def test_no_frames_at_all_raises():
    from b601.cameras.reference import stable_landmarks
    with pytest.raises(DriftError, match="at least"):
        stable_landmarks([])
