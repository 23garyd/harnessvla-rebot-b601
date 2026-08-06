"""Apply the camera manifest to the hardware, and prove it took.

`b601.cameras.config` records what the cameras are supposed to be.
`b601.cameras.sync` checks what they delivered. This is the piece in between:
it puts the recorded configuration onto the devices, which is the step where
"the manifest says fixed exposure" becomes true rather than aspirational.

WHY EVERY WRITE IS READ BACK. Measured on epyc 2026-08-06, both cameras:

  - The UVC camera SILENTLY IGNORES a write to `exposure_time_absolute` while
    it is in Aperture Priority mode. The control reads `flags=inactive` until
    `auto_exposure=1` (Manual Mode) is selected, and V4L2 reports the write as
    successful either way. Order matters, and success is not evidence.
  - The two backends disagree about what "off" is: V4L2 auto exposure is
    disabled with the value 1 (Manual Mode) — there is no 0 on this device —
    while RealSense uses 0. That is why the backend is a RECORDED manifest
    field and not inferred from the model string.
  - Persistence differs too. V4L2 control state lives in the driver and
    survived process exit; the D405 reverted to auto exposure and 33000 us the
    moment the pipeline stopped. Neither may be relied upon between sessions,
    so this runs every time rather than once by hand.

A setting that did not take is an ERROR, never a warning. A session that
silently ran under auto exposure produces episodes indistinguishable from
correct ones afterwards, and the sim track's lesson is that a systematic
perception bias is unrecoverable once it is in the data.

Backends are injected. The whole module is testable with no cameras attached,
which is the same discipline the safety layer follows.

WHAT THIS DOES NOT COVER:

  - It sets only what the manifest records. Brightness, contrast, sharpness,
    backlight compensation and the rest keep whatever the driver defaults to.
    They are not varied deliberately, but they are not pinned either.
  - Reading a value back proves the control accepted it, NOT that the sensor
    honoured it. A camera can report exposure 8000 and expose differently.
  - It does not verify the image. A correctly configured camera with the lens
    cap on passes every check here.
  - `verify_mode` compares what the driver reported it negotiated. A driver
    that misreports its own mode is not detectable from this side.
"""
from dataclasses import dataclass

# Devices quantise to their own step, so a value a hair off is the device being
# a device. An order-of-magnitude difference is a write that did not take.
EXPOSURE_TOLERANCE_FRACTION = 0.05
GAIN_TOLERANCE_FRACTION = 0.05


class CaptureError(Exception):
    """A camera could not be configured as the manifest describes."""


@dataclass(frozen=True)
class AppliedSettings:
    """What the hardware actually accepted. Returned rather than assumed: the
    achieved value is what the episodes get recorded under, and if it differs
    from the manifest then the manifest is what needs correcting."""
    name: str
    exposure: float
    gain: float
    auto_exposure: bool
    auto_white_balance: object      # None when the backend has no such control

    @property
    def matches_manifest(self):
        return self._matches

    _matches: bool = True


def _verify(backend, control, requested, tolerance, camera, label):
    actual = backend.get(control)
    if abs(actual - requested) > max(tolerance * abs(requested), 1e-9):
        raise CaptureError(
            f"{camera.name}: {label} did not take — asked for {requested:g}, "
            f"device reports {actual:g}. On V4L2 this is what an inactive "
            f"control looks like: the write succeeds and the value does not "
            f"move. The camera is NOT configured as cameras.json describes")
    return actual


def _disable_auto(backend, control, camera, label):
    """Turn an automatic control off and confirm it is off.

    Booleans, not driver values: the backend owns the translation, because
    'off' is 1 on this V4L2 device and 0 on RealSense.
    """
    if not backend.supports(control):
        return None
    backend.set(control, False)
    if backend.get(control):
        raise CaptureError(
            f"{camera.name}: {label} would not turn off (still reports "
            f"{backend.get(control)!r}). Recording under it makes ambient "
            f"light a hidden variable that is indistinguishable from policy "
            f"error afterwards")
    return False


def apply_settings(camera, backend):
    """-> AppliedSettings. Applies `camera`'s recorded configuration.

    Automatic controls are disabled BEFORE the values they gate are written,
    because on V4L2 the absolute exposure control is inactive until Manual Mode
    is selected and a write to it is silently dropped.
    """
    auto_exposure = _disable_auto(backend, "auto_exposure", camera,
                                  "auto exposure")
    auto_white_balance = _disable_auto(backend, "auto_white_balance", camera,
                                       "auto white balance")

    if not backend.supports("exposure"):
        raise CaptureError(
            f"{camera.name}: backend exposes no exposure control, so the fixed "
            f"exposure this manifest records cannot be applied")
    backend.set("exposure", camera.exposure)
    exposure = _verify(backend, "exposure", camera.exposure,
                       EXPOSURE_TOLERANCE_FRACTION, camera, "exposure")

    gain = camera.gain
    if backend.supports("gain"):
        backend.set("gain", camera.gain)
        gain = _verify(backend, "gain", camera.gain, GAIN_TOLERANCE_FRACTION,
                       camera, "gain")

    return AppliedSettings(
        name=camera.name,
        exposure=exposure,
        gain=gain,
        auto_exposure=False if auto_exposure is False else auto_exposure,
        auto_white_balance=auto_white_balance,
        _matches=(exposure == camera.exposure and gain == camera.gain),
    )


def verify_mode(camera, negotiated):
    """Confirm the driver negotiated the mode the manifest records.

    A camera asked for a mode it cannot deliver may hand back a different one
    without complaining, and the manifest would then describe a configuration
    no episode was recorded under. Compared exactly — 29.97 is not 30, and
    rounding float frame rates into agreement is how the mismatch survives.
    """
    want = (camera.width, camera.height, camera.fps)
    got = tuple(negotiated)
    if want != got:
        raise CaptureError(
            f"{camera.name}: negotiated {got[0]}x{got[1]}@{got[2]} but "
            f"cameras.json records {want[0]}x{want[1]}@{want[2]}. Either the "
            f"camera could not deliver the recorded mode or the manifest is "
            f"wrong; recording under the difference makes the manifest a "
            f"description of something that did not happen")


def configure(cameras, backends):
    """-> {name: AppliedSettings} for every camera in the manifest.

    A camera with no backend is an error rather than a skip: skipping would
    leave it on auto exposure while the report said the manifest was applied.
    """
    applied = {}
    for camera in cameras:
        backend = backends.get(camera.name)
        if backend is None:
            raise CaptureError(
                f"{camera.name}: no backend supplied, so its recorded "
                f"configuration would go unapplied while the rest succeeded")
        applied[camera.name] = apply_settings(camera, backend)
    return applied


# --- backends -------------------------------------------------------------
#
# Thin adapters. All they do is translate the semantic control names above into
# each driver's own vocabulary — which is exactly where the risk is, because the
# two drivers disagree about what "off" means.

_V4L2_CONTROLS = {
    "auto_exposure": "auto_exposure",
    "auto_white_balance": "white_balance_automatic",
    "exposure": "exposure_time_absolute",
    "gain": "gain",
}
# This device's auto_exposure is a MENU, not a bool: 1 = Manual Mode,
# 3 = Aperture Priority. There is no 0, so writing the usual boolean False
# fails and leaves the camera on auto. white_balance_automatic beside it IS a
# plain bool, so the two cannot share one translation.
_V4L2_MANUAL_EXPOSURE = 1
_V4L2_AUTO_EXPOSURE = 3


def _v4l2_run(args):
    import subprocess
    done = subprocess.run(["v4l2-ctl"] + args, capture_output=True, text=True)
    if done.returncode != 0:
        raise CaptureError(f"v4l2-ctl {' '.join(args)} failed: {done.stderr.strip()}")
    return done.stdout


class V4L2Backend:
    """UVC cameras, driven through v4l2-ctl.

    Supported controls are PROBED from the device rather than assumed: a camera
    without a white-balance control must report it absent, not have writes
    quietly discarded.
    """

    def __init__(self, device, run=_v4l2_run):
        self._device = device
        self._run = run
        listing = run(["-d", device, "-l"])
        self._present = {line.split()[0] for line in listing.splitlines()
                         if line.strip()}

    def supports(self, control):
        return _V4L2_CONTROLS.get(control) in self._present

    def get(self, control):
        name = _V4L2_CONTROLS[control]
        out = self._run(["-d", self._device, "-C", name])
        raw = float(out.split(":", 1)[1].strip().split()[0])
        if control == "auto_exposure":
            return raw != _V4L2_MANUAL_EXPOSURE
        if control == "auto_white_balance":
            return bool(raw)
        return raw

    def set(self, control, value):
        name = _V4L2_CONTROLS[control]
        if control == "auto_exposure":
            value = _V4L2_AUTO_EXPOSURE if value else _V4L2_MANUAL_EXPOSURE
        elif control == "auto_white_balance":
            value = 1 if value else 0
        self._run(["-d", self._device, "-c", f"{name}={int(value)}"])


class RealSenseBackend:
    """RealSense sensors, driven through pyrealsense2 options.

    Constructed with the SENSOR, not the device: the D405 has no separate RGB
    sensor, so colour and its exposure control both live on the Stereo Module.
    Unlike V4L2, these revert when the pipeline stops, so this must run after
    every `pipeline.start()`.
    """

    def __init__(self, sensor, options=None):
        self._sensor = sensor
        if options is None:                      # imported lazily: the suite
            import pyrealsense2 as rs           # must not need librealsense
            options = {"auto_exposure": rs.option.enable_auto_exposure,
                       "exposure": rs.option.exposure,
                       "gain": rs.option.gain}
        self._options = options

    def supports(self, control):
        option = self._options.get(control)
        return option is not None and self._sensor.supports(option)

    def get(self, control):
        value = self._sensor.get_option(self._options[control])
        return bool(value) if control == "auto_exposure" else value

    def set(self, control, value):
        # RealSense uses 0/1 here, where the V4L2 device above uses 1/3.
        if control == "auto_exposure":
            value = 1.0 if value else 0.0
        self._sensor.set_option(self._options[control], float(value))


def open_backend(camera):
    """-> a backend for `camera`, chosen by its RECORDED `backend` field.

    Never inferred from the model string: the field exists precisely so that
    "auto exposure off" resolves to 1 on the V4L2 camera and 0 on the D405.
    """
    if camera.backend == "v4l2":
        return V4L2Backend(camera.device)
    if camera.backend == "realsense":
        import pyrealsense2 as rs
        for device in rs.context().devices:
            if device.get_info(rs.camera_info.serial_number) != camera.serial:
                continue
            for sensor in device.sensors:
                if sensor.supports(rs.option.exposure):
                    return RealSenseBackend(sensor)
            raise CaptureError(
                f"{camera.name}: RealSense {camera.serial} exposes no sensor "
                f"with an exposure control")
        raise CaptureError(
            f"{camera.name}: no RealSense with serial {camera.serial} is "
            f"attached; cameras.json describes hardware that is not here")
    raise CaptureError(f"{camera.name}: unknown backend {camera.backend!r}")


def main(argv=None, open_backend=open_backend):
    """`python -m b601.cameras.capture` — put cameras.json onto the hardware.

    Run it before every recording session, not once by hand: V4L2 settings are
    reset by a replug or a reboot, and RealSense options revert the moment the
    pipeline stops. Exit 0 means every recorded setting was written AND read
    back; exit 1 means at least one camera is not configured as the manifest
    describes, which is a reason not to record.

    It does NOT open a stream, so it cannot check the negotiated mode — that is
    `verify_mode`, called by whatever starts the capture.
    """
    import sys
    from b601.cameras.config import CameraManifestError, load_cameras

    argv = list(sys.argv[1:] if argv is None else argv)
    if argv:
        print("usage: python -m b601.cameras.capture", file=sys.stderr)
        return 64
    try:
        cameras = load_cameras()
        applied = configure(cameras, {c.name: open_backend(c) for c in cameras})
    except (CameraManifestError, CaptureError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    by_name = {c.name: c for c in cameras}
    drifted = False
    for name, settings in applied.items():
        camera = by_name[name]
        print(f"  {name:<14} exposure {settings.exposure:g}  "
              f"gain {settings.gain:g}  auto-exposure off  "
              f"auto-WB {'off' if settings.auto_white_balance is False else 'n/a'}")
        if not settings.matches_manifest:
            drifted = True
            print(f"    NOTE: achieved exposure {settings.exposure:g} / gain "
                  f"{settings.gain:g} differs from cameras.json "
                  f"({camera.exposure:g} / {camera.gain:g}) — the device "
                  f"quantised. Record the achieved values, since those are "
                  f"what the episodes will be recorded under")
    print("cameras configured from cameras.json"
          + (" (with quantisation, see above)" if drifted else ""))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
