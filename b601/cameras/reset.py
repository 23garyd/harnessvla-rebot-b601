"""Hardware-reset the D405 so the NEXT pipeline session is the good one.

MEASURED on this camera (firmware 5.12.14.100, USB 3.2): the D405 delivers
frames on exactly ONE pipeline session per hardware reset. Every later session
opens, negotiates the correct profile, and streams nothing — 0/30 frames after
0s, 5s and 15s of waiting — until the next reset. Setting options WITHOUT a
pipeline (what `b601.cameras.capture` does) does not consume the session, and
options set that way persist into the next session.

So the recording script runs this AFTER preflight (whose liveness grab
consumes a session) and BEFORE lerobot-record (the opener that matters), then
re-applies the manifest settings the reset wiped.

Two waiting rules, both measured:
  - the device disappears from enumeration and returns seconds later, so
    reappearance is polled rather than assumed;
  - it enumerates several seconds BEFORE it can stream, so a settle delay
    follows reappearance. Returning at first sight of the serial would hand
    the next opener a camera that is visible but not ready — the same silent
    0-frame failure this module exists to end.
"""
from dataclasses import dataclass


class ResetError(Exception):
    """The camera could not be reset or did not come back. Never proceed."""


@dataclass(frozen=True)
class ResetReport:
    serial: str
    waited_s: float

    def summary(self):
        return f"RESET OK  {self.serial} re-enumerated after {self.waited_s:.1f}s"


def reset_and_wait(serial, reset_fn, list_serials, sleep,
                   timeout_s=60.0, poll_s=2.0, settle_s=4.0):
    """Reset, poll until the serial re-enumerates, then settle. -> ResetReport

    `reset_fn`, `list_serials` and `sleep` are injected so the unpowered suite
    can run this; production wiring lives in `main`.
    """
    if timeout_s <= 0:
        raise ValueError("timeout_s must be positive: a zero wait cannot "
                         "distinguish a returned camera from a vanished one")
    if serial not in list_serials():
        raise ResetError(
            f"{serial} is not attached; cannot reset a camera that is not "
            f"here. Check the cable before anything else")

    reset_fn()

    waited = 0.0
    while waited < timeout_s:
        sleep(poll_s)
        waited += poll_s
        if serial in list_serials():
            sleep(settle_s)  # enumerated is not ready — measured gap
            return ResetReport(serial=serial, waited_s=waited)

    raise ResetError(
        f"{serial} did not re-enumerate within {timeout_s:.0f}s of a hardware "
        f"reset. The camera has effectively been unplugged — replug it and "
        f"re-run")


def _reset_realsense(serial, timeout_s=60.0):
    """Production wiring: pyrealsense2, imported lazily so the unpowered
    suite never needs librealsense."""
    import time

    import pyrealsense2 as rs

    def list_serials():
        return {device.get_info(rs.camera_info.serial_number)
                for device in rs.context().devices}

    def reset_fn():
        for device in rs.context().devices:
            if device.get_info(rs.camera_info.serial_number) == serial:
                device.hardware_reset()
                return
        raise ResetError(f"{serial} disappeared between the attachment check "
                         f"and the reset")

    return reset_and_wait(serial, reset_fn=reset_fn, list_serials=list_serials,
                          sleep=time.sleep, timeout_s=timeout_s)


def main(argv=None, reset=_reset_realsense):
    """`python -m b601.cameras.reset` — reset every RealSense in the manifest.

    Only RealSense cameras: the webcam has no single-session defect and no
    hardware_reset, so touching it would add failure modes for nothing.
    """
    import sys

    from b601.cameras.config import CameraManifestError, load_cameras

    argv = list(sys.argv[1:] if argv is None else argv)
    if argv:
        print("usage: python -m b601.cameras.reset", file=sys.stderr)
        return 64
    try:
        for camera in load_cameras():
            if camera.backend != "realsense":
                continue
            print(reset(camera.serial).summary())
    except (CameraManifestError, ResetError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
