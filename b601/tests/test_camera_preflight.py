"""One gate to run before a recording session, and the gap it closes.

`capture.py` proves the settings took. `sync.py` proves the streams were
aligned. `reference.py` proves the mounts have not moved. None of them proves
the camera is ALIVE — and measured on this machine, a D405 whose pipeline had
wedged returned entirely correct option values while `wait_for_frames` timed out
for ten seconds. Configuration and liveness are different properties, and only
one of them was being checked.

So liveness is checked first and separately: grab frames, count them, and treat
a shortfall as a failure that names what it means. Everything else is
composition — the point of this module is that an operator runs ONE command and
gets one exit code, rather than remembering four.
"""
import pytest

from b601.cameras.preflight import (LivenessReport, check_liveness, summarise)


def live(name="agentview", requested=30, received=30, timed_out=False):
    return check_liveness(name, requested, received, timed_out)


class FakeSync:
    def __init__(self, passed=True):
        self.passed = passed

    def summary(self):
        return "SYNC OK" if self.passed else "SYNC FAILED"


class FakeDrift:
    def __init__(self, name="agentview", passed=True):
        self.name, self.passed = name, passed

    def summary(self):
        return f"{'DRIFT OK' if self.passed else 'DRIFT DETECTED'}  {self.name}"


# --- liveness --------------------------------------------------------------

def test_a_camera_delivering_every_frame_passes():
    assert live().passed


def test_a_camera_that_timed_out_fails():
    """THE CASE THIS EXISTS FOR. Measured: correct settings, zero frames."""
    r = live(received=0, timed_out=True)
    assert not r.passed
    assert "0/30" in r.summary()


def test_the_failure_says_configuration_is_not_liveness():
    """The operator has just seen the capture tool report success. The message
    has to explain why that is not a contradiction."""
    r = live(received=0, timed_out=True)
    assert "configured" in r.summary().lower()


def test_a_partial_delivery_fails_rather_than_rounding_up():
    """29 of 30 is a camera dropping frames, not a camera that is fine."""
    r = live(received=29)
    assert not r.passed
    assert "29/30" in r.summary()


def test_receiving_more_than_requested_is_not_a_failure():
    assert live(received=31).passed


def test_zero_requested_is_rejected_rather_than_vacuously_passing():
    """Requesting no frames and receiving none must not read as healthy."""
    with pytest.raises(ValueError, match="at least one"):
        check_liveness("agentview", 0, 0, False)


# --- aggregation -----------------------------------------------------------

def test_everything_green_passes_overall():
    ok, text = summarise([live()], FakeSync(), [FakeDrift()], ())
    assert ok
    assert "PREFLIGHT OK" in text


def test_a_dead_camera_fails_overall_even_when_sync_and_drift_are_clean():
    ok, text = summarise([live(received=0, timed_out=True)], FakeSync(),
                         [FakeDrift()], ())
    assert not ok
    assert "PREFLIGHT FAILED" in text


def test_a_sync_failure_fails_overall():
    ok, _ = summarise([live()], FakeSync(passed=False), [FakeDrift()], ())
    assert not ok


def test_a_drift_failure_fails_overall():
    ok, _ = summarise([live()], FakeSync(), [FakeDrift(passed=False)], ())
    assert not ok


def test_every_section_appears_in_the_report_even_when_it_passed():
    """An operator reading a green report should see WHAT was checked. A gate
    that prints nothing on success teaches people it does nothing."""
    _, text = summarise([live()], FakeSync(), [FakeDrift()], ())
    assert "agentview" in text
    assert "SYNC OK" in text
    assert "DRIFT OK" in text


def test_cameras_with_no_drift_reference_are_named_as_unchecked():
    _, text = summarise([live()], FakeSync(), [FakeDrift()], ("eye_in_hand",))
    assert "NOT CHECKED" in text
    assert "eye_in_hand" in text


def test_no_liveness_reports_at_all_fails_rather_than_passing_vacuously():
    """Zero cameras checked is not zero problems found."""
    ok, text = summarise([], FakeSync(), [FakeDrift()], ())
    assert not ok
    assert "no cameras" in text.lower()
