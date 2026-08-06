"""Applying the manifest to the cameras, and proving it took.

`cameras.json` records the configuration; this is what puts it on the hardware.
The gap between those two is not theoretical. Measured on 2026-08-06:

  - the UVC camera silently IGNORES a write to `exposure_time_absolute` while
    it is in Aperture Priority mode, because the control reads `flags=inactive`
    until `auto_exposure=1`. The write returns success. The value does not move.
  - the D405 REVERTED to auto exposure and 33000 us the moment the capture
    pipeline stopped, while the UVC camera's settings persisted after the
    process exited. Neither behaviour can be relied on.

So every write is read back, and a value that did not take is an error rather
than a log line — a recording session that silently ran under auto exposure
produces episodes that cannot be distinguished from correct ones afterwards.

Backends are injected, so all of this is tested with no cameras attached.
"""
import pytest

from b601.cameras.capture import (CaptureError, apply_settings, configure,
                                  verify_mode)
from b601.cameras.config import load_cameras


def camera(name="agentview"):
    return next(c for c in load_cameras() if c.name == name)


class FakeBackend:
    """Records the order of operations, which is half of what is under test."""

    def __init__(self, supported=("auto_exposure", "exposure", "gain",
                                  "auto_white_balance"),
                 ignore=(), quantise=None):
        self.values = {"auto_exposure": True, "auto_white_balance": True,
                       "exposure": 33000.0, "gain": 99.0}
        self._supported = set(supported)
        self._ignore = set(ignore)
        self._quantise = quantise or {}
        self.calls = []

    def supports(self, control):
        return control in self._supported

    def get(self, control):
        return self.values[control]

    def set(self, control, value):
        self.calls.append((control, value))
        if control in self._ignore:
            return                                   # the silent-ignore case
        if control in self._quantise:
            value = self._quantise[control]
        self.values[control] = value


# --- ordering -------------------------------------------------------------

def test_auto_exposure_is_disabled_before_the_exposure_value_is_written():
    """THE ORDERING TRAP. On V4L2 the absolute exposure control is inactive
    until Manual Mode is selected, so writing the value first is a no-op that
    reports success."""
    b = FakeBackend()
    apply_settings(camera(), b)
    written = [c for c, _ in b.calls]
    assert written.index("auto_exposure") < written.index("exposure")


def test_auto_white_balance_is_disabled_before_anything_else_is_trusted():
    b = FakeBackend()
    apply_settings(camera(), b)
    assert ("auto_white_balance", False) in b.calls


# --- the values come from the manifest ------------------------------------

def test_exposure_and_gain_are_taken_from_the_manifest():
    cam = camera("eye_in_hand")
    b = FakeBackend()
    applied = apply_settings(cam, b)
    assert b.values["exposure"] == cam.exposure
    assert b.values["gain"] == cam.gain
    assert applied.exposure == cam.exposure
    assert applied.auto_exposure is False


def test_nothing_is_invented_for_a_control_the_manifest_does_not_carry():
    """Only the recorded fields are written. A capture path that also set, say,
    a brightness it made up would be configuring the camera with a value no
    experiment record contains."""
    b = FakeBackend()
    apply_settings(camera(), b)
    assert {c for c, _ in b.calls} <= {"auto_exposure", "auto_white_balance",
                                       "exposure", "gain"}


# --- read-back verification ------------------------------------------------

def test_an_exposure_write_that_is_silently_ignored_raises():
    """The measured V4L2 failure: the write succeeds and the value does not
    move. Without a read-back the session records under auto exposure and
    nothing downstream can tell."""
    b = FakeBackend(ignore=("exposure",))
    with pytest.raises(CaptureError, match="exposure"):
        apply_settings(camera(), b)


def test_the_error_names_the_camera_and_both_values():
    b = FakeBackend(ignore=("exposure",))
    with pytest.raises(CaptureError) as exc:
        apply_settings(camera(), b)
    message = str(exc.value)
    assert "agentview" in message
    assert "156" in message and "33000" in message


def test_auto_exposure_that_refuses_to_turn_off_raises():
    b = FakeBackend(ignore=("auto_exposure",))
    with pytest.raises(CaptureError, match="auto exposure"):
        apply_settings(camera(), b)


def test_a_gain_write_that_is_ignored_raises():
    b = FakeBackend(ignore=("gain",))
    with pytest.raises(CaptureError, match="gain"):
        apply_settings(camera(), b)


def test_device_quantisation_within_tolerance_is_accepted_and_reported():
    """Devices round to their own step. A value one unit off is the device
    being a device, not a write being dropped — but the ACHIEVED value is what
    the episodes were recorded under, so it is returned rather than assumed."""
    cam = camera("eye_in_hand")
    b = FakeBackend(quantise={"exposure": cam.exposure - 1})
    applied = apply_settings(cam, b)
    assert applied.exposure == cam.exposure - 1
    assert applied.exposure != cam.exposure


def test_quantisation_beyond_tolerance_is_not_excused():
    cam = camera("eye_in_hand")
    b = FakeBackend(quantise={"exposure": cam.exposure * 0.5})
    with pytest.raises(CaptureError, match="exposure"):
        apply_settings(cam, b)


# --- unsupported controls --------------------------------------------------

def test_a_control_the_backend_does_not_have_is_skipped_not_fatal():
    """The D405's Stereo Module has no white-balance control at all. Absent is
    not the same as present-and-automatic."""
    b = FakeBackend(supported=("auto_exposure", "exposure", "gain"))
    applied = apply_settings(camera("eye_in_hand"), b)
    assert applied.auto_white_balance is None
    assert "auto_white_balance" not in [c for c, _ in b.calls]


def test_a_backend_missing_exposure_entirely_still_raises():
    """Skipping white balance is defensible; skipping the control this whole
    module exists to fix is not."""
    b = FakeBackend(supported=("auto_exposure", "gain"))
    with pytest.raises(CaptureError, match="exposure"):
        apply_settings(camera(), b)


# --- negotiated mode -------------------------------------------------------

def test_a_negotiated_mode_matching_the_manifest_passes():
    verify_mode(camera(), (640, 480, 30))


@pytest.mark.parametrize("negotiated", [(1280, 720, 30), (640, 480, 15),
                                        (640, 360, 30)])
def test_a_negotiated_mode_that_differs_raises(negotiated):
    """A camera asked for a mode it cannot do may hand back a different one.
    The manifest would then describe a configuration that was never used."""
    with pytest.raises(CaptureError, match="negotiated"):
        verify_mode(camera(), negotiated)


def test_a_near_miss_frame_rate_is_still_a_mismatch():
    """29.97 is not 30. Float frame rates come back from V4L2 and must not be
    rounded into agreement."""
    with pytest.raises(CaptureError, match="negotiated"):
        verify_mode(camera(), (640, 480, 29.97))


# --- configuring the whole manifest ---------------------------------------

def test_configure_applies_every_camera_and_returns_what_was_achieved():
    cams = load_cameras()
    backends = {c.name: FakeBackend() for c in cams}
    applied = configure(cams, backends)
    assert set(applied) == {c.name for c in cams}
    for cam in cams:
        assert backends[cam.name].values["exposure"] == cam.exposure


def test_configure_names_the_camera_that_failed():
    cams = load_cameras()
    backends = {c.name: FakeBackend() for c in cams}
    backends["eye_in_hand"] = FakeBackend(ignore=("exposure",))
    with pytest.raises(CaptureError, match="eye_in_hand"):
        configure(cams, backends)


def test_configure_refuses_a_camera_with_no_backend():
    """Silently skipping it would leave that camera on auto exposure while the
    report said the manifest had been applied."""
    cams = load_cameras()
    backends = {cams[0].name: FakeBackend()}
    with pytest.raises(CaptureError, match="no backend"):
        configure(cams, backends)


# --- V4L2 backend: the value translation is the whole risk -----------------

CTRL_LISTING = """\
     white_balance_automatic 0x0098090c (bool)   : default=1 value=1
                        gain 0x00980913 (int)    : min=1 max=8 step=1 default=1 value=1
               auto_exposure 0x009a0901 (menu)   : min=0 max=3 default=3 value=3
      exposure_time_absolute 0x009a0902 (int)    : min=10 max=626 step=1 default=156 value=156
"""


class FakeRunner:
    """Stands in for v4l2-ctl. Records the -c arguments actually issued."""

    def __init__(self, listing=CTRL_LISTING):
        self.listing = listing
        self.written = []
        self.state = {"auto_exposure": 3, "white_balance_automatic": 1,
                      "exposure_time_absolute": 156, "gain": 1}

    def __call__(self, args):
        if "-l" in args or "--list-ctrls" in args:
            return self.listing
        flag = args[args.index("-c") + 1] if "-c" in args else None
        if flag and "=" in flag:
            key, value = flag.split("=", 1)
            self.written.append((key, int(value)))
            self.state[key] = int(value)
            return ""
        if "-C" in args:
            key = args[args.index("-C") + 1]
            return f"{key}: {self.state[key]}\n"
        return ""


def v4l2(runner):
    from b601.cameras.capture import V4L2Backend
    return V4L2Backend("/dev/null", run=runner)


def test_v4l2_disables_auto_exposure_with_manual_mode_which_is_one_not_zero():
    """THE TRAP. This device's auto_exposure menu offers 1 (Manual Mode) and 3
    (Aperture Priority) — there is no 0. Writing 0 fails, and a backend that
    assumed the usual boolean would leave the camera on auto."""
    r = FakeRunner()
    v4l2(r).set("auto_exposure", False)
    assert ("auto_exposure", 1) in r.written


def test_v4l2_disables_auto_white_balance_with_zero_which_is_a_real_bool():
    """And the neighbouring control IS a plain bool, so the two cannot share a
    translation."""
    r = FakeRunner()
    v4l2(r).set("auto_white_balance", False)
    assert ("white_balance_automatic", 0) in r.written


def test_v4l2_reads_auto_exposure_back_as_a_boolean():
    r = FakeRunner()
    b = v4l2(r)
    assert b.get("auto_exposure") is True         # 3 = Aperture Priority
    b.set("auto_exposure", False)
    assert b.get("auto_exposure") is False        # 1 = Manual Mode


def test_v4l2_maps_exposure_to_the_absolute_control():
    r = FakeRunner()
    v4l2(r).set("exposure", 156)
    assert ("exposure_time_absolute", 156) in r.written


def test_v4l2_support_is_probed_from_the_device_not_assumed():
    """A camera without a white-balance control must report it absent rather
    than have writes silently discarded."""
    without = "\n".join(l for l in CTRL_LISTING.splitlines()
                        if "white_balance" not in l)
    assert v4l2(FakeRunner()).supports("auto_white_balance")
    assert not v4l2(FakeRunner(listing=without)).supports("auto_white_balance")


def test_a_real_v4l2_camera_is_configured_end_to_end_through_apply_settings():
    r = FakeRunner()
    applied = apply_settings(camera("agentview"), v4l2(r))
    order = [k for k, _ in r.written]
    assert order.index("auto_exposure") < order.index("exposure_time_absolute")
    assert applied.exposure == 156 and applied.auto_exposure is False


# --- RealSense backend -----------------------------------------------------

class FakeOption:
    def __init__(self, name):
        self.name = name

    def __hash__(self):
        return hash(self.name)

    def __eq__(self, other):
        return isinstance(other, FakeOption) and other.name == self.name


class FakeSensor:
    def __init__(self, absent=()):
        self.values = {"enable_auto_exposure": 1.0, "exposure": 33000.0,
                       "gain": 16.0}
        self._absent = set(absent)

    def supports(self, opt):
        return opt.name not in self._absent and opt.name in self.values

    def get_option(self, opt):
        return self.values[opt.name]

    def set_option(self, opt, value):
        self.values[opt.name] = value


def realsense(sensor):
    from b601.cameras.capture import RealSenseBackend
    options = {"auto_exposure": FakeOption("enable_auto_exposure"),
               "exposure": FakeOption("exposure"),
               "gain": FakeOption("gain")}
    return RealSenseBackend(sensor, options=options)


def test_realsense_disables_auto_exposure_with_zero_unlike_v4l2():
    s = FakeSensor()
    realsense(s).set("auto_exposure", False)
    assert s.values["enable_auto_exposure"] == 0.0


def test_realsense_reports_no_white_balance_control_on_the_stereo_module():
    """The D405 has no separate RGB sensor and no white-balance control. Absent
    must not read as present-and-automatic."""
    assert not realsense(FakeSensor()).supports("auto_white_balance")


def test_a_real_d405_is_configured_end_to_end_through_apply_settings():
    s = FakeSensor()
    applied = apply_settings(camera("eye_in_hand"), realsense(s))
    assert s.values["enable_auto_exposure"] == 0.0
    assert s.values["exposure"] == 8000.0
    assert s.values["gain"] == 16.0
    assert applied.auto_white_balance is None


# --- the command the operator runs ----------------------------------------

def fake_factory(failing=()):
    def open_backend(cam):
        return FakeBackend(ignore=("exposure",) if cam.name in failing else ())
    return open_backend


def test_main_configures_every_camera_and_exits_zero(capsys):
    from b601.cameras.capture import main
    assert main([], open_backend=fake_factory()) == 0
    out = capsys.readouterr().out
    assert "agentview" in out and "eye_in_hand" in out


def test_main_exits_nonzero_and_names_the_camera_that_would_not_configure(capsys):
    """This gates a recording session, so it must fail loudly rather than
    leaving one camera on auto exposure and reporting success."""
    from b601.cameras.capture import main
    assert main([], open_backend=fake_factory(failing=("eye_in_hand",))) == 1
    assert "eye_in_hand" in capsys.readouterr().err


def test_main_reports_the_achieved_value_when_the_device_quantised(capsys):
    """The manifest is meant to describe what the episodes were recorded under.
    If the hardware rounded, the operator has to know to correct the file."""
    from b601.cameras.capture import main

    def open_backend(cam):
        return FakeBackend(quantise={"exposure": cam.exposure - 1})

    assert main([], open_backend=open_backend) == 0
    assert "differs from cameras.json" in capsys.readouterr().out
