"""The D405 streams exactly ONE pipeline session per hardware reset.

MEASURED on this camera (firmware 5.12.14.100, USB 3.2, pyrealsense2 in the
robot env): after a hardware reset the first pipeline session delivers every
frame; the second and every later session opens successfully, negotiates the
right profile, and then delivers nothing — 0/30 after waiting 0s, 5s and 15s.
Only another hardware reset restores it.

That is why recording attempt 4 died: preflight's liveness grab consumed the
one good session, and lerobot-record — the opener that matters — got the dead
one. The fix is an explicit reset between the last diagnostic session and the
recording session, plus re-applying the manifest settings the reset wiped.

This module tests the reset step. The hardware calls are injected because the
suite must run unpowered; what is being tested is the WAITING DISCIPLINE —
a reset that returns before the camera is actually back, or that reports
success for a camera that never returned, recreates the silent 0-frame
failure this exists to end.
"""
import pytest

from b601.cameras.reset import ResetError, reset_and_wait


class FakeCamera:
    """A camera that disappears on reset and returns after `absent_polls`."""

    def __init__(self, serial="353322271941", absent_polls=3, attached=True,
                 comes_back=True):
        self.serial = serial
        self._attached = attached
        self._absent_polls = absent_polls
        self._comes_back = comes_back
        self.resets = 0
        self.polls = 0
        self.sleeps = []

    def reset_fn(self):
        self.resets += 1
        self._attached = False

    def list_serials(self):
        self.polls += 1
        if not self._attached and self._comes_back and self.polls >= self._absent_polls:
            self._attached = True
        return {self.serial} if self._attached else set()

    def sleep(self, seconds):
        self.sleeps.append(seconds)


def test_a_camera_that_comes_back_is_reported_reset():
    cam = FakeCamera()
    report = reset_and_wait(cam.serial, reset_fn=cam.reset_fn,
                            list_serials=cam.list_serials, sleep=cam.sleep)
    assert cam.resets == 1
    assert cam.serial in report.summary()
    assert "RESET OK" in report.summary()


def test_a_camera_that_is_not_attached_cannot_be_reset():
    """Resetting nothing must not report success — the next gate would then
    open a camera that was never reset and get the dead session."""
    cam = FakeCamera(attached=False)
    with pytest.raises(ResetError, match="not attached"):
        reset_and_wait(cam.serial, reset_fn=cam.reset_fn,
                       list_serials=cam.list_serials, sleep=cam.sleep)
    assert cam.resets == 0


def test_a_camera_that_never_returns_fails_with_the_timeout_named():
    """The operator's remedy is physical (replug), so the message must say
    the camera vanished rather than leaving a bare timeout."""
    cam = FakeCamera(comes_back=False)
    with pytest.raises(ResetError, match="did not re-enumerate"):
        reset_and_wait(cam.serial, reset_fn=cam.reset_fn,
                       list_serials=cam.list_serials, sleep=cam.sleep,
                       timeout_s=10.0)


def test_the_settle_delay_comes_after_reappearance():
    """MEASURED: the device enumerates seconds before it can stream. A reset
    step that returns at first sight of the serial hands the next opener a
    camera that is visible but not ready — the same silent failure again,
    now caused by the fix."""
    cam = FakeCamera()
    reset_and_wait(cam.serial, reset_fn=cam.reset_fn,
                   list_serials=cam.list_serials, sleep=cam.sleep,
                   settle_s=4.0)
    assert cam.sleeps[-1] == 4.0


def test_a_nonpositive_timeout_is_rejected_not_vacuously_passed():
    cam = FakeCamera()
    with pytest.raises(ValueError, match="positive"):
        reset_and_wait(cam.serial, reset_fn=cam.reset_fn,
                       list_serials=cam.list_serials, sleep=cam.sleep,
                       timeout_s=0)


# --- the CLI resets exactly the cameras that need it ------------------------

def test_main_resets_only_realsense_cameras(tmp_path, capsys):
    """The webcam has no single-session defect and no hardware_reset; a reset
    step that touched it would add failure modes for nothing."""
    from b601.cameras.reset import main
    seen = []

    def fake_reset(serial, **kwargs):
        seen.append(serial)
        from b601.cameras.reset import ResetReport
        return ResetReport(serial=serial, waited_s=6.0)

    assert main([], reset=fake_reset) == 0
    assert seen == ["353322271941"]
    assert "RESET OK" in capsys.readouterr().out


def test_main_fails_loudly_when_the_reset_fails(capsys):
    from b601.cameras.reset import main

    def fake_reset(serial, **kwargs):
        raise ResetError(f"{serial} did not re-enumerate within 60s")

    assert main([], reset=fake_reset) == 1
    assert "did not re-enumerate" in capsys.readouterr().err
