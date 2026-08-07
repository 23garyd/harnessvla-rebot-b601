"""Agreeing on a nominal frame rate is not the same as delivering aligned frames.

`load_cameras` refuses a manifest whose cameras disagree on frame rate. That is
a check on intent. This module checks DELIVERY: what the cameras actually
produced, which on USB 2.1 with two cameras on one host is not the same thing.

Why it matters here specifically. The wrist camera is the only sensor that can
verify a grasp (sim finding 4), and the fixed camera is what the planner
re-grounds from (finding 1). If frame i of one stream and frame i of the other
show instants 40 ms apart, then the verification and the scene estimate
disagree about where the arm was — and the dataset records them as one
observation. That defect is invisible afterwards and permanent, exactly like the
sim track's stale reference coordinate.

The checker is pure, like `limits.py`: timestamps in, report out, no cameras and
no filesystem. That is what lets it run in CI, and it is also what bounds what
it can possibly know — enumerated in the module docstring rather than left to be
discovered.
"""
import json
import math

import pytest

from b601.cameras.sync import (SyncError, check_stream, check_sync, main)

FPS = 30
PERIOD = 1.0 / FPS


def perfect(n=30, offset=0.0, fps=FPS):
    return [offset + i / fps for i in range(n)]


# --- per-stream rate ------------------------------------------------------

def test_a_clean_stream_reports_the_expected_interval():
    r = check_stream("agentview", perfect(), FPS)
    assert r.frames == 30
    assert r.dropped == 0
    assert r.expected_interval_s == pytest.approx(PERIOD)
    assert r.mean_interval_s == pytest.approx(PERIOD)
    assert r.max_jitter_s < 1e-9


def test_a_dropped_frame_is_counted_not_averaged_away():
    """A gap of two frame periods is a missing frame. Averaged into a mean
    interval it disappears; ACT consumes the stream as evenly spaced."""
    ts = perfect(30)
    del ts[10]
    r = check_stream("agentview", ts, FPS)
    assert r.dropped == 1
    assert r.max_interval_s == pytest.approx(2 * PERIOD)


def test_several_dropped_frames_are_each_counted():
    ts = perfect(60)
    del ts[40]
    del ts[20]
    del ts[10]
    assert check_stream("agentview", ts, FPS).dropped == 3


def test_a_long_stall_counts_every_missing_frame_not_just_one_gap():
    """Five frame periods of silence is four missing frames, not one event.
    Counting gaps rather than frames would under-report a USB stall."""
    ts = perfect(20)
    ts = ts[:10] + [t + 4 * PERIOD for t in ts[10:]]
    assert check_stream("agentview", ts, FPS).dropped == 4


def test_a_stream_delivering_below_its_requested_rate_is_visible():
    """The failure the D405 on USB 2.1 is most likely to produce: it accepts a
    30 fps request and delivers fewer. The mean interval must show it rather
    than the report claiming the requested rate back."""
    r = check_stream("eye_in_hand", perfect(30, fps=22), FPS)
    assert r.mean_interval_s == pytest.approx(1 / 22)
    assert r.mean_interval_s > r.expected_interval_s
    # 1/22 - 1/30 is 12.1 ms, which is 0.36 of a frame period — under the half
    # frame that bounds jitter and offset. So a stream quietly delivering 22 fps
    # instead of 30 is NOT caught by either of those bounds, and needs its own.
    assert r.rate_error_frames == pytest.approx(0.3636, abs=1e-3)


def test_a_stream_below_its_requested_rate_fails_the_check():
    """The companion to the above: measuring the shortfall is not enough, the
    verdict has to reject it. Every interval is evenly spaced and no frame is
    missing relative to its own cadence, so jitter and drop counting both see
    a clean stream. Only the rate bound catches it."""
    rep = check_sync({"eye_in_hand": perfect(30, fps=22)}, FPS)
    assert not rep.passed
    assert "rate" in rep.summary()


# --- per-stream validation ------------------------------------------------

def test_non_monotonic_timestamps_raise_rather_than_being_sorted():
    """Out-of-order timestamps mean the recorder is wrong. Sorting them would
    manufacture a clean stream out of a broken one."""
    ts = perfect(10)
    ts[4], ts[5] = ts[5], ts[4]
    with pytest.raises(SyncError, match="monotonic"):
        check_stream("agentview", ts, FPS)


def test_duplicate_timestamps_raise():
    """Two frames stamped identically cannot both be an observation instant."""
    ts = perfect(10)
    ts[5] = ts[4]
    with pytest.raises(SyncError, match="monotonic"):
        check_stream("agentview", ts, FPS)


@pytest.mark.parametrize("bad", [float("nan"), float("inf")])
def test_non_finite_timestamp_raises(bad):
    """NaN passes every naive comparison, as the safety layer documents."""
    ts = perfect(10)
    ts[3] = bad
    with pytest.raises(SyncError, match="finite"):
        check_stream("agentview", ts, FPS)


def test_a_stream_too_short_to_have_an_interval_raises():
    with pytest.raises(SyncError, match="at least two"):
        check_stream("agentview", [0.0], FPS)


@pytest.mark.parametrize("bad", [0, -30])
def test_non_positive_fps_raises(bad):
    with pytest.raises(SyncError, match="fps"):
        check_stream("agentview", perfect(), bad)


# --- cross-stream alignment -----------------------------------------------

def test_identical_streams_are_perfectly_aligned_and_pass():
    rep = check_sync({"agentview": perfect(), "eye_in_hand": perfect()}, FPS)
    assert rep.pair_gap_p95_s < 1e-9
    assert rep.passed


def test_a_small_constant_offset_still_passes():
    """Cameras on separate USB controllers will never be bit-aligned. A 5 ms
    skew at 30 fps is 0.15 of a frame and is not a defect."""
    rep = check_sync({"agentview": perfect(),
                      "eye_in_hand": perfect(offset=0.005)}, FPS)
    assert rep.pair_gap_p95_s == pytest.approx(0.005)
    assert rep.passed


def test_two_free_running_cameras_that_drift_apart_still_pass():
    """MEASURED ON THIS MACHINE, and the reason the first version of this
    module was wrong. The D405 delivered a mean interval of 33.30 ms while the
    UVC camera delivered 33.02 ms — both within a whisker of 30 fps, but 0.28
    ms/frame apart. Compared index against index that accumulates without
    bound: 76 ms after 150 frames, and more the longer the episode runs, so a
    long episode would fail however good the cameras are.

    It is not a defect. Two USB cameras with no hardware sync ALWAYS drift, and
    a recorder pairs each observation with the most recent frame from each
    camera by timestamp — never by frame index. Under that pairing the streams
    stay within a fraction of a frame period, which is what must be asserted.
    """
    drifting = [i / 29.5 for i in range(300)]
    rep = check_sync({"agentview": perfect(300), "eye_in_hand": drifting}, FPS)
    assert rep.max_index_offset_s > 4 * PERIOD      # index pairing looks awful
    assert rep.pair_gap_p95_s < 0.5 * PERIOD        # timestamp pairing is fine
    assert rep.passed


def test_the_index_offset_and_drift_rate_are_still_reported():
    """Drift does not fail the check, but it is the number that says a
    frame-index recorder would be wrong, so it must not be silently dropped."""
    drifting = [i / 29.5 for i in range(300)]
    rep = check_sync({"agentview": perfect(300), "eye_in_hand": drifting}, FPS)
    assert rep.drift_s_per_frame == pytest.approx(1 / 29.5 - 1 / 30, abs=1e-6)
    assert "drift" in rep.summary()
    assert "timestamp" in rep.summary()


def test_frames_outside_the_overlapping_window_are_excluded_and_counted():
    """MEASURED: capturing 150 frames from each of two cameras at slightly
    different rates leaves the slower stream still running after the faster one
    stopped. Those trailing frames have no counterpart because capture ended,
    not because the cameras were out of sync — pairing them reported a 69.8 ms
    max gap on a recording that was fine. They are excluded from the pairing
    metric and counted, so the exclusion is visible rather than silent.
    """
    a = perfect(50)
    b = [t + 0.5 for t in perfect(50)]
    rep = check_sync({"agentview": a, "eye_in_hand": b}, FPS)
    assert rep.unpaired_frames > 0
    assert rep.pair_gap_max_s <= 0.5 * PERIOD + 1e-9
    assert "unpaired" in rep.summary()


def test_a_stalled_stream_fails_because_no_frame_is_near_the_other_stream():
    """What the cross-stream check is actually for once drift is excluded: a
    camera that stops delivering leaves observations with no contemporaneous
    frame, and nearest-timestamp pairing is what exposes it."""
    stalled = perfect(60)
    stalled = stalled[:30] + [t + 10 * PERIOD for t in stalled[30:]]
    rep = check_sync({"agentview": perfect(60), "eye_in_hand": stalled}, FPS)
    assert not rep.passed
    assert rep.pair_gap_max_s > 2 * PERIOD


def test_a_leading_buffered_frame_does_not_by_itself_fail_the_check():
    """MEASURED: the UVC capture's first two intervals were 6.0 ms and 13.6 ms
    — buffered frames flushing after the stream started — and everything after
    them was clean. Judging on MAX jitter made the verdict hostage to a startup
    artifact that every V4L2 capture produces, so the bound is on p95."""
    # The two short intervals are at the FRONT and the stream then runs clean
    # from where it got to — the shape actually measured, and no frame is lost.
    ts = [0.0, 0.006, 0.0196]
    ts += [ts[-1] + (i + 1) * PERIOD for i in range(147)]
    rep = check_sync({"agentview": ts}, FPS)
    assert rep.streams[0].dropped == 0
    assert rep.streams[0].max_jitter_s > 0.5 * PERIOD    # still reported
    assert rep.streams[0].jitter_p95_s < 0.25 * PERIOD
    assert rep.passed


def test_sustained_jitter_still_fails():
    """The p95 bound must not become a way for a genuinely irregular stream to
    pass. Every other frame late by a full period is not a startup artifact."""
    # 0.45 of a period each way: every interval still rounds to one frame, so
    # this fails on irregularity alone rather than being caught as a drop.
    ts = [i * PERIOD + (0.45 * PERIOD if i % 2 else 0) for i in range(150)]
    rep = check_sync({"agentview": ts}, FPS)
    assert rep.streams[0].dropped == 0
    assert not rep.passed
    assert "jitter" in rep.summary()


def test_a_dropped_frame_in_either_stream_fails_the_check():
    ts = perfect(30)
    del ts[10]
    rep = check_sync({"agentview": perfect(30), "eye_in_hand": ts}, FPS)
    assert not rep.passed
    assert "dropped" in rep.summary()


def test_unequal_frame_counts_are_reported_and_fail():
    """Different lengths mean the streams cannot be zipped into observations at
    all. Comparing the common prefix and staying silent would hide it."""
    rep = check_sync({"agentview": perfect(30),
                      "eye_in_hand": perfect(25)}, FPS)
    assert not rep.passed
    assert rep.frame_counts == {"agentview": 30, "eye_in_hand": 25}
    assert "count" in rep.summary()


def test_a_single_stream_is_allowed_and_has_no_offset():
    """Rate and drops are still worth checking with one camera; there is just
    nothing to be misaligned with."""
    rep = check_sync({"agentview": perfect()}, FPS)
    assert rep.max_index_offset_s == 0.0
    assert rep.pair_gap_p95_s == 0.0
    assert rep.drift_s_per_frame == 0.0
    assert rep.passed


def test_a_constant_offset_larger_than_half_a_frame_cannot_be_detected():
    """A BLIND SPOT, asserted so it is not mistaken for coverage.

    With free-running cameras, "20 ms late" and "13 ms early on the next frame"
    are the same observation sequence. Nearest-timestamp pairing therefore
    aliases any constant offset into at most half a frame period, and no
    arrival-time analysis can tell them apart. Measuring a real constant
    latency difference needs a physical event visible to both cameras.
    """
    rep = check_sync({"agentview": perfect(),
                      "eye_in_hand": perfect(offset=0.020)}, FPS)
    assert rep.pair_gap_p95_s <= 0.5 * PERIOD + 1e-9
    assert rep.passed


def test_no_streams_raises():
    with pytest.raises(SyncError, match="no streams"):
        check_sync({}, FPS)


def test_report_names_every_stream_it_checked():
    rep = check_sync({"agentview": perfect(), "eye_in_hand": perfect()}, FPS)
    assert {s.name for s in rep.streams} == {"agentview", "eye_in_hand"}


# --- the command Day 3 actually runs -------------------------------------

def recording(tmp_path, streams, fps=None):
    payload = {"streams": streams}
    if fps is not None:
        payload["fps"] = fps
    p = tmp_path / "timestamps.json"
    p.write_text(json.dumps(payload))
    return str(p)


def test_main_exits_zero_on_a_clean_recording(tmp_path, capsys):
    path = recording(tmp_path, {"agentview": perfect(),
                                "eye_in_hand": perfect(offset=0.002)}, fps=FPS)
    assert main([path]) == 0
    assert "SYNC OK" in capsys.readouterr().out


def test_main_exits_nonzero_on_a_bad_recording(tmp_path, capsys):
    """The operator must be able to tell from the exit code alone, so this can
    gate a recording session rather than being read by eye.

    A wrist camera quietly delivering 22 fps against a requested 30 is the
    realistic failure on this hardware — the D405 is on a USB 2.1 link — and
    unlike a constant offset it is genuinely detectable from timestamps.
    """
    path = recording(tmp_path, {"agentview": perfect(),
                                "eye_in_hand": perfect(fps=22)}, fps=FPS)
    assert main([path]) == 1
    assert "SYNC FAILED" in capsys.readouterr().out


def test_main_checks_against_the_manifest_rate_when_the_recording_omits_it(
        tmp_path, capsys):
    """A rate retyped into the recording is a rate that can disagree with the
    manifest the cameras were configured from. Absent an explicit fps, the
    declared one is used — the same reasoning as URDF_EE_FRAME being read from
    the driver rather than typed a second time into the pin."""
    from b601.cameras.config import load_cameras, record_fps
    declared = record_fps(load_cameras())
    path = recording(tmp_path, {"agentview": perfect(30, fps=declared)})
    assert main([path]) == 0
    assert f"{declared:.2f} fps requested" in capsys.readouterr().out


def test_main_reports_usage_without_arguments(capsys):
    assert main([]) == 64


def test_main_fails_on_a_missing_file(tmp_path, capsys):
    assert main([str(tmp_path / "nope.json")]) == 1
    assert "not found" in capsys.readouterr().err


def test_main_fails_on_malformed_json(tmp_path, capsys):
    p = tmp_path / "bad.json"
    p.write_text("{not json")
    assert main([str(p)]) == 1
    assert "not valid JSON" in capsys.readouterr().err


def test_main_fails_rather_than_defaulting_when_streams_are_absent(tmp_path,
                                                                  capsys):
    p = tmp_path / "empty.json"
    p.write_text(json.dumps({"fps": FPS}))
    assert main([str(p)]) == 1
    assert "streams" in capsys.readouterr().err


def test_main_surfaces_a_broken_recorder_as_an_error_not_a_failed_check(
        tmp_path, capsys):
    """Non-monotonic timestamps are not "the cameras were out of sync", they
    are "this recording cannot be interpreted". Those must not read the same."""
    ts = perfect(10)
    ts[4], ts[5] = ts[5], ts[4]
    assert main([recording(tmp_path, {"agentview": ts}, fps=FPS)]) == 1
    assert "monotonic" in capsys.readouterr().err


def test_tolerance_is_configurable_and_stricter_tolerance_can_fail(tmp_path):
    """Day 3 may want a tighter bound than half a frame once the real numbers
    are known. The default must not be the only option."""
    streams = {"agentview": perfect(), "eye_in_hand": perfect(offset=0.005)}
    assert check_sync(streams, FPS).passed
    assert not check_sync(streams, FPS, offset_tolerance_frames=0.1).passed


def test_streams_that_do_not_overlap_in_time_cannot_pass():
    """FOUND ON HARDWARE. Preflight grabbed the cameras sequentially, so the
    two streams were 4.2 s apart and shared no common window. Every frame was
    excluded from pairing, the gap list was left holding only its seed, and the
    checker reported a 0.00 ms pairing gap and PASSED — a perfect score for
    comparing nothing. Structural blindness of exactly the kind the pin probes
    were fixed for."""
    a = perfect(60)
    b = [t + 10.0 for t in perfect(60)]      # starts after a has finished
    rep = check_sync({"agentview": a, "eye_in_hand": b}, FPS)
    assert rep.pairs_compared == 0
    assert not rep.passed
    assert "overlap" in rep.summary()


def test_a_single_stream_still_passes_with_no_pairs():
    """The seed that caused the bug is correct for one stream: there is
    genuinely nothing to pair against, and that is not a failure."""
    rep = check_sync({"agentview": perfect()}, FPS)
    assert rep.pairs_compared == 0
    assert rep.passed
