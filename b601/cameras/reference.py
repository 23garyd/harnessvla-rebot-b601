"""Detect that a camera mount moved, without a metric calibration.

THE FAILURE THIS GUARDS. Sim finding 3: a stale reference coordinate produced
release errors of +0.078-0.082 m and inverted the strongest cell in the
evaluation matrix, and no audit caught it, because the bad number never entered
an action — it biased which estimate the planner SELECTED. The physical
analogue is a nudged camera mount. It is equally silent, and every episode
recorded after the nudge carries a systematic perception bias that is
indistinguishable from policy error at evaluation time.

A full camera-to-robot calibration would catch it. So does something much
cheaper, and this is it: fixed ArUco landmarks in view, their pixel positions
recorded once, compared at the start of every session. That is also exactly what
`calibration_report.md` asks for when it requires "evidence that landmarks are
stable across a restart".

WHY LANDMARKS AND NOT THE WHOLE IMAGE. Comparing frames wholesale — pixel
difference, or feature matching across the scene — flags drift every time an
object moves, and objects move in every episode because moving them is the task.
Markers fixed at the workspace periphery, outside the manipulation area, are
immune to that and to residual lighting variation.

The comparison is PURE — positions in, report out, no OpenCV and no filesystem —
so it runs in CI with no cameras. Detection is a thin adapter, the same split the
capture backends use.

WHAT THIS DOES NOT COVER:

  - It is NOT a calibration. It gives no intrinsics and no camera-to-robot
    transform, so it cannot convert a pixel into a position. It detects CHANGE
    from a reference, nothing more.
  - It cannot tell a moved CAMERA from moved LANDMARKS. Both show up as
    displacement. Fix the markers to the same structure the workspace is fixed
    to, and treat any drift as a reason to stop and look.
  - It says nothing about the wrist camera unless the arm is at a repeatable
    pose. A moving camera's landmarks move legitimately, so `eye_in_hand` has no
    reference until a fixed pose exists to capture one at. `check_all` reports
    that as UNCHECKED rather than passing it.
  - A uniform scale change (camera moved along its optical axis) shows up as
    displacement only for landmarks away from the principal point. Markers
    clustered near the image centre would weaken it.
  - It does not verify focus, exposure or that the image is of anything useful.
"""
import json
import math
from dataclasses import dataclass
from pathlib import Path

DEFAULT_CALIBRATION = Path(__file__).resolve().parents[1] / "setup" / "calibration.json"


class DriftError(Exception):
    """The drift check could not be performed. Never swallow this."""


@dataclass(frozen=True)
class DriftReport:
    name: str
    median_displacement_px: float
    max_displacement_px: float
    tolerance_px: float
    landmarks_checked: int
    missing: tuple
    extra: tuple

    @property
    def reasons(self):
        out = []
        if self.missing:
            out.append(
                f"{len(self.missing)} reference landmark(s) missing from the "
                f"current view: {list(self.missing)} — a landmark that cannot "
                f"be seen has not been verified")
        if self.median_displacement_px > self.tolerance_px:
            out.append(
                f"mount drift: median landmark displacement "
                f"{self.median_displacement_px:.2f} px exceeds "
                f"{self.tolerance_px:.2f} px")
        return tuple(out)

    @property
    def passed(self):
        return not self.reasons

    def summary(self):
        head = "DRIFT OK" if self.passed else "DRIFT DETECTED"
        lines = [f"{head}  {self.name}: {self.landmarks_checked} landmark(s), "
                 f"median {self.median_displacement_px:.2f} px, "
                 f"max {self.max_displacement_px:.1f} px "
                 f"(tolerance {self.tolerance_px:.2f} px)"]
        if self.extra:
            lines.append(f"  extra landmark(s) in view, not checked: "
                         f"{list(self.extra)}")
        for reason in self.reasons:
            lines.append(f"  FAIL: {reason}")
        return "\n".join(lines)


def compare_landmarks(name, reference, current, tolerance_px):
    """-> DriftReport for one camera.

    `reference` and `current` map landmark id -> (x, y) in pixels.

    The verdict uses the MEDIAN displacement, deliberately. A mount that moved
    displaces every landmark together; one marker knocked askew displaces one.
    The median answers the first question, which is the one that invalidates
    episodes. A single displaced landmark still surfaces through
    `max_displacement_px` rather than passing unseen.
    """
    if not reference:
        # A comparison against nothing passes forever while checking nothing —
        # the structural blindness the pin probes were fixed for.
        raise DriftError(
            f"{name}: the reference records no landmarks, so there is nothing "
            f"to compare against")

    missing = tuple(sorted(i for i in reference if i not in current))
    extra = tuple(sorted(i for i in current if i not in reference))
    shared = [i for i in sorted(reference) if i in current]

    displacements = []
    for i in shared:
        (rx, ry), (cx, cy) = reference[i], current[i]
        displacements.append(math.dist((rx, ry), (cx, cy)))

    if displacements:
        ordered = sorted(displacements)
        mid = len(ordered) // 2
        median = (ordered[mid] if len(ordered) % 2
                  else (ordered[mid - 1] + ordered[mid]) / 2)
        largest = max(ordered)
    else:
        median = largest = 0.0

    return DriftReport(
        name=name,
        median_displacement_px=median,
        max_displacement_px=largest,
        tolerance_px=float(tolerance_px),
        landmarks_checked=len(shared),
        missing=missing,
        extra=extra,
    )


@dataclass(frozen=True)
class ReferenceSet:
    """The stored artifact. This file is what `CALIBRATION_SHA256` pins, so a
    change to it is a registry event: it redefines what "not drifted" means."""
    method: str
    dictionary: str
    tolerance_px: float
    cameras: dict          # name -> {landmark id: (x, y)}

    def write(self, path):
        path = Path(path)
        payload = {
            "_note": [
                "Landmark drift reference. NOT a metric calibration: no",
                "intrinsics, no camera-to-robot transform. It detects that a",
                "mount MOVED, which is the failure that silently biases every",
                "episode recorded afterwards (sim finding 3).",
                "Pinned by CALIBRATION_SHA256 in pins.env. Re-recording it",
                "redefines 'not drifted' and is a registry event.",
            ],
            "method": self.method,
            "dictionary": self.dictionary,
            "tolerance_px": self.tolerance_px,
            "cameras": {
                name: {str(i): list(xy) for i, xy in sorted(marks.items())}
                for name, marks in sorted(self.cameras.items())
            },
        }
        path.write_text(json.dumps(payload, indent=2) + "\n")


def load_reference(path=None):
    """-> ReferenceSet. Raises on anything it cannot fully validate."""
    path = Path(path) if path is not None else DEFAULT_CALIBRATION
    if not path.is_file():
        raise DriftError(f"calibration reference not found: {path}")
    try:
        raw = json.loads(path.read_text())
    except ValueError as exc:
        raise DriftError(f"{path}: not valid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise DriftError(f"{path}: expected a mapping")

    cameras = raw.get("cameras")
    if not isinstance(cameras, dict) or not cameras:
        raise DriftError(f"{path}: records no cameras")
    tolerance = raw.get("tolerance_px")
    if not isinstance(tolerance, (int, float)) or isinstance(tolerance, bool) \
            or tolerance <= 0:
        raise DriftError(
            f"{path}: tolerance_px must be a positive number, got "
            f"{tolerance!r}")

    parsed = {}
    for name, marks in cameras.items():
        if not isinstance(marks, dict):
            raise DriftError(f"{path}: {name}: landmarks must be a mapping")
        out = {}
        for key, xy in marks.items():
            try:
                i = int(key)
                x, y = (float(v) for v in xy)
            except (TypeError, ValueError) as exc:
                raise DriftError(
                    f"{path}: {name}: bad landmark {key!r}: {exc}") from exc
            out[i] = (x, y)
        parsed[name] = out

    return ReferenceSet(method=str(raw.get("method", "")),
                        dictionary=str(raw.get("dictionary", "")),
                        tolerance_px=float(tolerance),
                        cameras=parsed)


def check_all(reference, detected):
    """-> (reports, unchecked) for every camera with a stored reference.

    `detected` maps camera name -> {landmark id: (x, y)} seen right now.

    A camera with NO reference is returned as `unchecked` rather than passed:
    the wrist camera has none, because its landmarks only mean anything at a
    repeatable arm pose, and "not checked" must never read as "checked and
    clean". A camera that HAS a reference but produced no detection at all is a
    different thing entirely and raises — it was supposed to be checked.
    """
    reports = []
    for name in sorted(reference.cameras):
        if name not in detected:
            raise DriftError(
                f"{name}: has a stored reference but produced no landmark "
                f"detection, so its mount could not be verified")
        reports.append(compare_landmarks(name, reference.cameras[name],
                                         detected[name],
                                         reference.tolerance_px))
    unchecked = tuple(sorted(n for n in detected if n not in reference.cameras))
    return reports, unchecked


# --- detection ------------------------------------------------------------

def detect_landmarks(frame, dictionary="DICT_4X4_50"):
    """-> {marker id: (x, y)} centre of each ArUco marker in `frame`.

    Centres rather than corners: a centre is the mean of four corners, so
    detection noise on any one corner is quartered, and it is a single number
    per landmark to compare. cv2 is imported lazily — the unpowered suite must
    not need OpenCV, the same rule the driver follows for placo.
    """
    import cv2
    import numpy as np
    try:
        predefined = getattr(cv2.aruco, dictionary)
    except AttributeError as exc:
        raise DriftError(f"unknown ArUco dictionary {dictionary!r}") from exc
    detector = cv2.aruco.ArucoDetector(
        cv2.aruco.getPredefinedDictionary(predefined),
        cv2.aruco.DetectorParameters())
    corners, ids, _ = detector.detectMarkers(frame)
    if ids is None:
        return {}
    found = {}
    for marker, i in zip(corners, ids.flatten()):
        centre = np.mean(marker.reshape(4, 2), axis=0)
        found[int(i)] = (float(centre[0]), float(centre[1]))
    return found


def grab_landmarks(cameras, dictionary="DICT_4X4_50"):
    """-> {camera name: {id: (x, y)}} by opening each camera for one frame.

    Applies the manifest's settings first: comparing a reference taken under
    fixed exposure against a frame taken under auto exposure would measure the
    lighting, not the mount.
    """
    from b601.cameras.capture import apply_settings, open_backend, verify_mode
    found = {}
    for camera in cameras:
        apply_settings(camera, open_backend(camera))
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
                for _ in range(30):            # let exposure settle
                    frames = pipe.wait_for_frames(5000)
                frame = np.asanyarray(frames.get_color_frame().get_data())
                frame = frame[:, :, ::-1]      # rgb8 -> BGR for cv2
            finally:
                pipe.stop()
        else:
            import cv2
            cap = cv2.VideoCapture(camera.device)
            try:
                cap.set(cv2.CAP_PROP_FOURCC,
                        cv2.VideoWriter_fourcc(*camera.format))
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, camera.width)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, camera.height)
                cap.set(cv2.CAP_PROP_FPS, camera.fps)
                if not cap.isOpened():
                    raise DriftError(f"{camera.name}: could not open "
                                     f"{camera.device}")
                for _ in range(30):
                    ok, frame = cap.read()
                verify_mode(camera, (int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
                                     int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
                                     int(cap.get(cv2.CAP_PROP_FPS))))
                if not ok:
                    raise DriftError(f"{camera.name}: no frame delivered")
            finally:
                cap.release()
        found[camera.name] = detect_landmarks(frame, dictionary)
    return found


DEFAULT_TOLERANCE_PX = 3.0
DEFAULT_DICTIONARY = "DICT_4X4_50"


def main(argv=None, grab=grab_landmarks, path=None):
    """`python -m b601.cameras.reference [--record]`

    Without --record: check every camera that has a stored reference and exit
    non-zero if any mount moved. Run it at the start of every session, before
    recording anything.

    With --record: capture the current landmark positions and write the
    artifact. This REDEFINES what "not drifted" means, so it is a registry
    event and `CALIBRATION_SHA256` must be re-recorded after it.
    """
    import sys
    from b601.cameras.config import load_cameras

    argv = list(sys.argv[1:] if argv is None else argv)
    if argv not in ([], ["--record"]):
        print("usage: python -m b601.cameras.reference [--record]",
              file=sys.stderr)
        return 64
    path = Path(path) if path is not None else DEFAULT_CALIBRATION

    try:
        cameras = load_cameras()
        detected = grab(cameras)
    except Exception as exc:                    # hardware, manifest, detection
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if argv == ["--record"]:
        # A camera showing no landmarks is NOT an error on its own: the wrist
        # camera legitimately has none, because a moving camera's landmarks
        # move with it and only mean anything at a repeatable arm pose. It is
        # recorded as un-referenced and reported, never skipped silently.
        seen = {n: m for n, m in detected.items() if m}
        empty = sorted(n for n, m in detected.items() if not m)
        if not seen:
            # Recording nothing would create a check that passes forever while
            # verifying nothing.
            print(f"ERROR: no landmarks visible to any camera "
                  f"({sorted(detected)}) — place ArUco markers "
                  f"({DEFAULT_DICTIONARY}) in view, fixed to the same "
                  f"structure as the workspace and outside the area objects "
                  f"move through", file=sys.stderr)
            return 1
        ReferenceSet(method="landmark_drift_reference",
                     dictionary=DEFAULT_DICTIONARY,
                     tolerance_px=DEFAULT_TOLERANCE_PX,
                     cameras=seen).write(path)
        for name, marks in sorted(seen.items()):
            print(f"  {name:<14} {len(marks)} landmark(s): {sorted(marks)}")
        if empty:
            print(f"  NOT REFERENCED (no landmarks in view): {empty} — these "
                  f"will report as NOT CHECKED and their mounts are unguarded")
        print(f"recorded drift reference -> {path}")
        print("This redefines 'not drifted': re-record CALIBRATION_SHA256 "
              "and add an experiment-registry entry")
        return 0

    try:
        reference = load_reference(path)
        reports, unchecked = check_all(reference, detected)
    except DriftError as exc:
        print(f"ERROR: {exc}\n       run "
              f"'python -m b601.cameras.reference --record' once the cameras "
              f"are in their final position", file=sys.stderr)
        return 1

    for report in reports:
        print(report.summary())
    if unchecked:
        # Absence of a failure must not read as evidence of no drift.
        print(f"  NOT CHECKED (no stored reference): {list(unchecked)}")
    return 0 if all(r.passed for r in reports) else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
