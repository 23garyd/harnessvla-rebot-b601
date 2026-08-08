"""The one command to run before a recording session.

THE GAP THIS CLOSES. `capture.py` proves the settings took. `sync.py` proves
the streams were aligned. `reference.py` proves the mounts have not moved. None
of them proves a camera is ALIVE. Measured on this machine 2026-08-06: a D405
whose pipeline had wedged returned entirely correct values for every option
while `wait_for_frames` timed out for ten seconds. A dead camera is
indistinguishable from a healthy one to anything that reads configuration
instead of frames — including `b601.cameras.capture`, whose docstring says so.

So liveness is checked first, separately, and by counting frames.

Everything else here is composition. The value is that an operator runs ONE
command and reads ONE exit code before recording, instead of remembering four
and getting the order wrong. The order is not arbitrary:

    1. apply the manifest      settings must be on before anything is measured
    2. verify the mode         a camera that renegotiated is not the one recorded
    3. LIVENESS                frames, not settings
    4. sync                    needs frames to exist before timing them
    5. drift                   needs correct exposure or it measures lighting

WHAT THIS DOES NOT COVER:

  - It does not look at the images. A correctly configured, live, in-sync
    camera with the lens cap on passes everything here.
  - It proves liveness AT PREFLIGHT TIME. A camera that stalls midway through
    episode 40 is not caught by a check that ran before episode 1; that needs
    a per-episode assertion in the recorder.
  - It cannot verify the wrist camera's mount (see `reference.py`).
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class LivenessReport:
    name: str
    requested: int
    received: int
    timed_out: bool

    @property
    def passed(self):
        return self.received >= self.requested and not self.timed_out

    def summary(self):
        head = "LIVE" if self.passed else "NO FRAMES"
        line = (f"  {head:<10} {self.name:<14} "
                f"{self.received}/{self.requested} frames")
        if not self.passed:
            line += ("\n    FAIL: the camera did not deliver. Note this is NOT "
                     "a contradiction of the capture tool reporting success — "
                     "a stalled camera reports perfectly correct settings "
                     "while configured and dead. Recover with a "
                     "hardware_reset() or a replug, and prefer one long-lived "
                     "pipeline over one per episode")
        return line


@dataclass(frozen=True)
class LinkReport:
    name: str
    descriptor: object          # None when it could not be read

    @property
    def passed(self):
        return bool(self.descriptor) and str(self.descriptor).startswith("3")

    def summary(self):
        shown = self.descriptor if self.descriptor else "unknown"
        head = "LINK OK" if self.passed else "LINK BAD"
        line = f"  {head:<10} {self.name:<14} USB {shown}"
        if not self.passed:
            line += ("\n    FAIL: a RealSense needs USB 3.x for headroom — "
                     "LeRobot itself warns 'Detected USB 2.1. Color/depth "
                     "streaming may stall', and the colour-only deviation in "
                     "the registry exists because depth+colour does not fit "
                     "in USB 2 bandwidth. Move it to a USB 3 port AND check "
                     "the cable: many USB-C cables are USB 2.0 only. (The "
                     "0-frame recording failure once blamed on this link was "
                     "actually two other defects — the vendor null-frame bug "
                     "and the D405's one-session-per-reset behaviour; see "
                     "risk_log.md)")
        return line


def check_usb_link(name, descriptor):
    """-> LinkReport. `descriptor` is librealsense's usb_type_descriptor.

    Unreadable counts as FAILED, not as fine: recording on an unverified link
    is exactly what failed.
    """
    return LinkReport(name=name, descriptor=descriptor)


def check_liveness(name, requested, received, timed_out):
    """-> LivenessReport. Pure; the grabbing lives in `main`."""
    if requested < 1:
        # Requesting nothing and receiving nothing must not read as healthy.
        raise ValueError(
            f"{name}: preflight must request at least one frame, got "
            f"{requested}")
    return LivenessReport(name=name, requested=int(requested),
                          received=int(received), timed_out=bool(timed_out))


def summarise(liveness, sync_report, drift_reports, unchecked, links=()):
    """-> (ok, text) aggregating every section into one verdict.

    Every section is printed even when it passed: a gate that prints nothing on
    success teaches the people running it that it does nothing, and then a
    failure looks like the tool being broken.
    """
    lines, ok = [], True

    if links:
        lines.append("links:")
        for report in links:
            lines.append(report.summary())
            ok = ok and report.passed

    lines.append("frames:")
    if not liveness:
        # Zero cameras checked is not zero problems found.
        ok = False
        lines.append("  FAIL: no cameras were checked, so nothing was verified")
    for report in liveness:
        lines.append(report.summary())
        ok = ok and report.passed

    lines.append("timing:")
    lines.append("  " + sync_report.summary().replace("\n", "\n  "))
    ok = ok and sync_report.passed

    lines.append("mounts:")
    for report in drift_reports:
        lines.append("  " + report.summary().replace("\n", "\n  "))
        ok = ok and report.passed
    if unchecked:
        lines.append(f"  NOT CHECKED (no stored reference): {list(unchecked)}")

    head = "PREFLIGHT OK" if ok else "PREFLIGHT FAILED"
    return ok, head + "\n" + "\n".join(lines)


FRAMES = 60


def main(argv=None):
    """`python -m b601.cameras.preflight` — run before every recording session.

    Exit 0 means: settings applied and read back, modes as recorded, every
    camera delivering, streams in sync, and no mount has moved since the drift
    reference was captured. Exit 1 means do not record yet.
    """
    import sys
    import time
    from b601.cameras.capture import (CaptureError, apply_settings,
                                      open_backend, verify_mode)
    from b601.cameras.config import (CameraManifestError, load_cameras,
                                     record_fps)
    from b601.cameras.reference import (MIN_STABILITY_FRAMES, DriftError,
                                        check_all, detect_landmarks,
                                        observed_landmarks,
                                        load_reference)
    from b601.cameras.sync import check_sync

    argv = list(sys.argv[1:] if argv is None else argv)
    if argv:
        print("usage: python -m b601.cameras.preflight", file=sys.stderr)
        return 64

    try:
        cameras = load_cameras()
    except CameraManifestError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    # Settings first, sequentially: applying them is cheap and must be done
    # before anything is measured.
    for camera in cameras:
        try:
            apply_settings(camera, open_backend(camera))
        except CaptureError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1

    # Then grab CONCURRENTLY. Grabbing one camera after another leaves the
    # streams with no overlapping window, and the sync check then has no frame
    # pairs to compare -- which it used to report as a flawless 0.00 ms gap.
    # Measured: sequential grabs put the two streams 4.2 s apart.
    import threading
    results, gate = {}, threading.Barrier(len(cameras) + 1)

    def worker(camera):
        try:
            results[camera.name] = _grab(camera, FRAMES, verify_mode, gate)
        except Exception as exc:                       # hardware failure
            results[camera.name] = (0, True, [], None)
            print(f"  {camera.name}: {type(exc).__name__}: {exc}",
                  file=sys.stderr)
            try:
                gate.wait(timeout=0.1)
            except Exception:
                pass

    threads = [threading.Thread(target=worker, args=(c,)) for c in cameras]
    for t in threads:
        t.start()
    try:
        gate.wait(timeout=60)
    except Exception as exc:
        print(f"  cameras did not all reach the start gate: {exc}",
              file=sys.stderr)
    for t in threads:
        t.join(timeout=120)

    links = []
    for camera in cameras:
        if camera.backend != "realsense":
            continue
        try:
            import pyrealsense2 as rs
            found = [d for d in rs.context().devices
                     if d.get_info(rs.camera_info.serial_number) == camera.serial]
            descriptor = (found[0].get_info(rs.camera_info.usb_type_descriptor)
                          if found else None)
        except Exception:
            descriptor = None
        links.append(check_usb_link(camera.name, descriptor))

    liveness, stamps, landmarks = [], {}, {}
    for camera in cameras:
        received, timed_out, ts, tail = results.get(
            camera.name, (0, True, [], []))
        liveness.append(check_liveness(camera.name, FRAMES, received,
                                       timed_out))
        if ts:
            stamps[camera.name] = ts
        if len(tail) >= MIN_STABILITY_FRAMES:
            # Vote over the burst: a landmark counts when seen in most frames
            # at one place. Single-frame detection made the drift gate a dice
            # roll — healthy inked tags measure 21-30/30 under room lighting.
            landmarks[camera.name] = observed_landmarks(
                [detect_landmarks(f) for f in tail])
        elif tail:
            landmarks[camera.name] = detect_landmarks(tail[-1])

    if not stamps:
        ok, text = summarise(liveness, _NoSync(), [], (), links=links)
        print(text)
        return 1

    sync_report = check_sync(stamps, record_fps(cameras))
    try:
        drift_reports, unchecked = check_all(load_reference(), landmarks)
    except DriftError as exc:
        drift_reports, unchecked = [], tuple(sorted(landmarks))
        print(f"  drift reference unavailable: {exc}", file=sys.stderr)

    ok, text = summarise(liveness, sync_report, drift_reports, unchecked,
                         links=links)
    print(text)
    return 0 if ok else 1


class _NoSync:
    passed = False

    def summary(self):
        return "SYNC NOT RUN: no camera produced timestamps"


def _grab(camera, frames, verify_mode, gate=None, keep=None):
    """-> (received, timed_out, timestamps, last_frames). Hardware.

    `last_frames` is a list of the trailing `keep` frames (default
    STABILITY_BURST from the reference module) rather than a single frame:
    the drift check votes over a burst — a landmark seen in most frames at
    one place — because per-frame dropout under room lighting made a
    single-frame check a dice roll on healthy tags (measured 21-30/30).

    `gate` is a barrier every camera waits on once it is OPEN but BEFORE it
    warms up, so the timed sections overlap. Without it the streams share no
    common window and the sync check has nothing to pair.

    The order matters and was measured: gating AFTER warm-up let V4L2 fill its
    buffer queue while the slower camera was still opening, and the queued
    frames then arrived back-to-back — 27 ms of jitter and a mean interval
    BELOW the frame period, which is a burst, not a camera. Warming up after
    the gate drains that queue.
    """
    import time
    from collections import deque

    from b601.cameras.reference import STABILITY_BURST
    tail = deque(maxlen=keep or STABILITY_BURST)
    if camera.backend == "realsense":
        import numpy as np
        import pyrealsense2 as rs
        pipe, cfg = rs.pipeline(), rs.config()
        cfg.enable_device(camera.serial)
        cfg.enable_stream(rs.stream.color, camera.width, camera.height,
                          rs.format.rgb8, camera.fps)
        profile = pipe.start(cfg)
        try:
            vp = profile.get_stream(rs.stream.color).as_video_stream_profile()
            verify_mode(camera, (vp.width(), vp.height(), vp.fps()))
            ts = []
            if gate is not None:
                gate.wait(timeout=60)
            for _ in range(30):
                pipe.wait_for_frames(5000)             # settle AND drain
            for _ in range(frames):
                got = pipe.wait_for_frames(5000)
                ts.append(time.perf_counter())
                tail.append(np.asanyarray(
                    got.get_color_frame().get_data())[:, :, ::-1])
            return len(ts), False, ts, list(tail)
        finally:
            pipe.stop()
    import cv2
    cap = cv2.VideoCapture(camera.device)
    try:
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*camera.format))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, camera.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, camera.height)
        cap.set(cv2.CAP_PROP_FPS, camera.fps)
        if not cap.isOpened():
            return 0, True, [], []
        if gate is not None:
            gate.wait(timeout=60)
        for _ in range(30):
            cap.read()
        verify_mode(camera, (int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
                             int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
                             int(cap.get(cv2.CAP_PROP_FPS))))
        ts = []
        for _ in range(frames):
            ok, got = cap.read()
            if not ok:
                return len(ts), True, ts, list(tail)
            ts.append(time.perf_counter())
            tail.append(got)
        return len(ts), False, ts, list(tail)
    finally:
        cap.release()


if __name__ == "__main__":
    import sys
    sys.exit(main())
