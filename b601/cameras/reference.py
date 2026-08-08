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
    # orb_homography only: name -> {"file", "sha256"}. The reference IMAGE is
    # what features are matched against, so its hash belongs in the artifact
    # that CALIBRATION_SHA256 pins -- otherwise the image could be swapped
    # under a pinned json and the check would silently mean something else.
    images: dict = None

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
        if self.images:
            payload["images"] = {k: dict(v) for k, v in sorted(self.images.items())}
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

    images = raw.get("images") or {}
    if not isinstance(images, dict):
        raise DriftError(f"{path}: 'images' must be a mapping")
    return ReferenceSet(method=str(raw.get("method", "")),
                        dictionary=str(raw.get("dictionary", "")),
                        tolerance_px=float(tolerance),
                        cameras=parsed,
                        images={k: dict(v) for k, v in images.items()})


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



# --- marker-free drift: homography over natural scene features -------------
#
# Measured on this workspace 2026-08-06: 1512 ORB features in the periphery,
# 609 of them strong. Markers are not required HERE because the scene carries
# enough texture on its own. Rather than invent a second verdict, the estimated
# homography is applied to a fixed grid of probe points and the displacement of
# THOSE is the drift — so both methods run through the same compare_landmarks.

# Fractions of the frame excluded from feature matching: objects move through
# the middle every episode, so only the border is a stable landmark region.
WORKSPACE_MASK = (0.20, 0.85, 0.15, 0.85)      # top, bottom, left, right
MIN_MATCH_INLIERS = 25


# A landmark must agree with itself across frames. MEASURED on this workspace:
# the cutting mat's grid makes ArUco hallucinate ids 10/17/22/34/37/38, each
# seen once at 6-18 px, and on one occasion id 190 in 10 of 12 frames with
# 108 px of jitter. Any of them recorded as a landmark would vanish on the next
# run and fail the check forever after, for no real reason.
MIN_STABILITY_FRAMES = 5
STABILITY_BURST = 12
DEFAULT_JITTER_PX = 2.0


def stable_landmarks(per_frame, max_jitter_px=DEFAULT_JITTER_PX):
    """-> {id: (x, y)} keeping only landmarks seen in EVERY frame at one place.

    `per_frame` is a list of {id: (x, y)} detections, one per frame. A landmark
    must appear in all of them and stay within `max_jitter_px`; the position
    returned is the mean, which also averages away detector noise.

    Presence in most frames is deliberately NOT enough. The worst phantom
    measured here was present in 10 of 12 frames — it was its 108 px of
    wandering that gave it away, not its rarity.
    """
    frames = list(per_frame)
    if len(frames) < MIN_STABILITY_FRAMES:
        raise DriftError(
            f"need at least {MIN_STABILITY_FRAMES} frames to tell a landmark "
            f"from a detector phantom, got {len(frames)}; a phantom looks "
            f"perfect in the one frame it appears in")

    common = set(frames[0])
    for f in frames[1:]:
        common &= set(f)

    out = {}
    for i in sorted(common):
        xs = [f[i][0] for f in frames]
        ys = [f[i][1] for f in frames]
        cx, cy = sum(xs) / len(xs), sum(ys) / len(ys)
        spread = max(max(abs(x - cx) for x in xs), max(abs(y - cy) for y in ys))
        if spread <= max_jitter_px:
            out[i] = (cx, cy)
    return out


def observed_landmarks(per_frame, max_jitter_px=DEFAULT_JITTER_PX):
    """-> {id: (x, y)} keeping landmarks seen in MOST frames at one place.

    The CHECK-time criterion, deliberately looser than `stable_landmarks`
    (which records references). Measured 2026-08-08: real inked tags at their
    reference positions detect in 21-30 of 30 frames with <=0.5 px spread,
    varying run to run with nothing physically changed — per-frame dropout
    under room lighting is detection noise, the same class of signal as V4L2
    timing jitter. Demanding perfect attendance made the session gate a dice
    roll on healthy hardware.

    What separates real landmarks from phantoms in every measurement this
    workspace has produced is POSITION, with rarity as a backstop: phantoms
    are rare (1-4 of 30, scattered ids) or they wander (10 of 12 frames with
    108 px of jitter). So: strictly more than half the frames, within the
    same jitter bound, position the mean over the frames where present.
    Presence must never outvote position.

    Recording stays with `stable_landmarks`: a reference should refuse
    marginal tags, and did — twice, correctly.
    """
    frames = list(per_frame)
    if len(frames) < MIN_STABILITY_FRAMES:
        raise DriftError(
            f"need at least {MIN_STABILITY_FRAMES} frames to tell a landmark "
            f"from a detector phantom, got {len(frames)}; a phantom looks "
            f"perfect in the one frame it appears in")

    ids = set().union(*[set(f) for f in frames])
    out = {}
    for i in sorted(ids):
        seen = [f[i] for f in frames if i in f]
        if len(seen) * 2 <= len(frames):        # a majority, strictly
            continue
        xs = [p[0] for p in seen]
        ys = [p[1] for p in seen]
        cx, cy = sum(xs) / len(xs), sum(ys) / len(ys)
        spread = max(max(abs(x - cx) for x in xs), max(abs(y - cy) for y in ys))
        if spread <= max_jitter_px:
            out[i] = (cx, cy)
    return out


def probe_grid(width, height, divisions=4):
    """-> {i: (x, y)} a deterministic grid of points spanning the frame.

    These are not features. They are fixed places whose movement UNDER the
    estimated homography is what gets measured, which keeps the units (pixels
    of displacement) and the verdict identical to the ArUco path. Spanning the
    frame matters: a rotation or a tilt barely moves the centre and moves the
    corners a lot.
    """
    points, i = {}, 0
    for row in range(1, divisions):
        for col in range(1, divisions):
            points[i] = (width * col / divisions, height * row / divisions)
            i += 1
    return points


def homography_landmarks(points, homography):
    """-> {i: (x, y)} for `points` mapped through a 3x3 `homography`.

    A homography cv2 could not estimate comes back as None. Treating that as
    "nothing moved" would be a check that passes precisely when it failed.
    """
    if homography is None:
        raise DriftError(
            "no homography could be estimated between the reference frame and "
            "the current one, so drift was NOT measured — too few matching "
            "features, or the scene changed beyond recognition")
    rows = [tuple(float(v) for v in row) for row in homography]
    if len(rows) != 3 or any(len(r) != 3 for r in rows):
        raise DriftError(f"homography must be 3x3, got {homography!r}")

    out = {}
    for i, (x, y) in points.items():
        w = rows[2][0] * x + rows[2][1] * y + rows[2][2]
        if abs(w) < 1e-12:
            raise DriftError(
                f"degenerate homography: probe point {i} maps to infinity, so "
                f"the estimate is unusable rather than merely large")
        # The third row is not decorative: without the division a camera that
        # TILTED rather than slid would under-report its drift.
        out[i] = ((rows[0][0] * x + rows[0][1] * y + rows[0][2]) / w,
                  (rows[1][0] * x + rows[1][1] * y + rows[1][2]) / w)
    return out


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


def estimate_homography(reference_gray, current_gray):
    """-> 3x3 homography mapping reference pixels to current ones.

    ORB features restricted to the frame periphery, matched with a ratio test,
    then RANSAC. RANSAC is what makes this usable without markers: a cable or a
    tool moved in the periphery produces outlier matches, and only a COHERENT
    shift across many features survives to move the estimate.
    """
    import cv2
    import numpy as np

    h, w = reference_gray.shape[:2]
    top, bottom, left, right = WORKSPACE_MASK
    mask = np.full((h, w), 255, np.uint8)
    mask[int(h * top):int(h * bottom), int(w * left):int(w * right)] = 0

    orb = cv2.ORB_create(nfeatures=2000)
    kp_ref, des_ref = orb.detectAndCompute(reference_gray, mask)
    kp_cur, des_cur = orb.detectAndCompute(current_gray, mask)
    if des_ref is None or des_cur is None or len(kp_ref) < MIN_MATCH_INLIERS:
        raise DriftError(
            f"too few features to compare: {0 if des_ref is None else len(kp_ref)} "
            f"in the reference, {0 if des_cur is None else len(kp_cur)} now. "
            f"The periphery may lack texture, or the view changed entirely")

    matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
    pairs = matcher.knnMatch(des_ref, des_cur, k=2)
    good = [m for m, n in (p for p in pairs if len(p) == 2)
            if m.distance < 0.75 * n.distance]
    if len(good) < MIN_MATCH_INLIERS:
        raise DriftError(
            f"only {len(good)} good feature matches (need "
            f"{MIN_MATCH_INLIERS}); drift was NOT measured")

    src = np.float32([kp_ref[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
    dst = np.float32([kp_cur[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
    H, inliers = cv2.findHomography(src, dst, cv2.RANSAC, 3.0)
    if H is None or inliers is None or int(inliers.sum()) < MIN_MATCH_INLIERS:
        raise DriftError(
            f"homography rejected: {0 if inliers is None else int(inliers.sum())} "
            f"RANSAC inliers of {len(good)} matches (need "
            f"{MIN_MATCH_INLIERS})")
    return tuple(tuple(float(v) for v in row) for row in H)


def grab_frames(cameras, burst=1):
    """-> {camera name: BGR frame, or list of frames when burst > 1}.

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
                    pipe.wait_for_frames(5000)
                shots = []
                for _ in range(burst):
                    got = pipe.wait_for_frames(5000)
                    shots.append(np.asanyarray(
                        got.get_color_frame().get_data())[:, :, ::-1])
                frame = shots if burst > 1 else shots[0]
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
                shots = []
                for _ in range(30):
                    ok, got = cap.read()
                for _ in range(burst):
                    ok, got = cap.read()
                    if ok and got is not None:
                        shots.append(got)
                frame = (shots if burst > 1 else (shots[0] if shots else None))
                verify_mode(camera, (int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
                                     int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
                                     int(cap.get(cv2.CAP_PROP_FPS))))
                if not shots:
                    raise DriftError(f"{camera.name}: no frame delivered")
            finally:
                cap.release()
        found[camera.name] = frame
    return found


ARUCO_METHOD = "aruco_landmarks"
ORB_METHOD = "orb_homography"
DEFAULT_TOLERANCE_PX = 3.0
DEFAULT_DICTIONARY = "DICT_4X4_50"


def _sha256(path):
    import hashlib
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def current_landmarks(reference, frames, path, detect=None):
    """-> {name: {id: (x, y)}} for the CURRENT frames, by the stored method.

    ArUco: detect the markers. ORB: match against the stored reference image
    and push the probe grid through the resulting homography. Either way the
    output is landmark positions, so the verdict is the same code.
    """
    detect = detect or detect_landmarks
    base = Path(path).parent
    out = {}
    for name, frame in frames.items():
        burst = frame if isinstance(frame, list) else [frame]
        if reference.method != ORB_METHOD and len(burst) >= MIN_STABILITY_FRAMES:
            # ArUco over the whole burst: a check accepts a landmark seen in
            # most frames at one place (measured: healthy tags drop frames
            # under room lighting; phantoms are rare or they wander).
            out[name] = observed_landmarks(
                [detect(shot, reference.dictionary or DEFAULT_DICTIONARY)
                 for shot in burst])
            continue
        frame = burst[-1]
        if reference.method == ORB_METHOD:
            if name not in reference.images:
                # No reference for it (a wrist camera). Carry it through as
                # empty so check_all reports it NOT CHECKED: dropping it here
                # would make it vanish from the report entirely, which reads
                # as "everything was checked".
                out[name] = {}
                continue
            record = reference.images[name]
            image_path = base / record["file"]
            if not image_path.is_file():
                raise DriftError(
                    f"{name}: reference image {image_path} is missing, so "
                    f"drift cannot be measured")
            if _sha256(image_path) != record.get("sha256"):
                # The pinned json vouches for this hash; a changed image under
                # it would silently redefine what "not drifted" means.
                raise DriftError(
                    f"{name}: reference image {image_path} does not match the "
                    f"hash recorded in the calibration artifact")
            import cv2
            ref_gray = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
            cur_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            H = estimate_homography(ref_gray, cur_gray)
            out[name] = homography_landmarks(reference.cameras[name], H)
        else:
            out[name] = detect(frame, reference.dictionary
                               or DEFAULT_DICTIONARY)
    return out


def main(argv=None, grab=grab_frames, path=None, detect=None):
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
        # A burst either way: recording demands a landmark in EVERY frame
        # (stable_landmarks); checking accepts a positionally-tight majority
        # (observed_landmarks). A single frame made the check a dice roll —
        # measured: healthy inked tags detect in 21-30 of 30 frames.
        frames = grab(cameras, burst=STABILITY_BURST)
    except Exception as exc:                    # hardware, manifest, detection
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if argv == ["--record"]:
        return _record(frames, path, detect or detect_landmarks)

    try:
        reference = load_reference(path)
        detected = current_landmarks(reference, frames, path, detect)
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


def _record(frames, path, detect):
    """Capture the reference, choosing the method the scene can actually support."""
    import sys
    from b601.cameras.config import load_cameras

    mounts = {c.name: c.mount for c in load_cameras()}
    # Only FIXED mounts get a reference. A wrist camera's view changes with
    # every arm pose, so its landmarks would measure the arm rather than the
    # mount and the check would fail constantly for the wrong reason. It needs
    # a repeatable arm pose first, which does not exist until safe_home is
    # trusted.
    moving = sorted(n for n in frames if mounts.get(n) not in (None, "fixed"))
    live = {n: f for n, f in frames.items()
            if f is not None and mounts.get(n, "fixed") == "fixed"}
    if not live:
        print("ERROR: no camera produced a frame, so there is nothing to "
              "record", file=sys.stderr)
        return 1

    # A burst per camera, then only landmarks that agree across ALL of it.
    # Measured here: the mat grid hallucinates a marker in roughly one frame in
    # fifteen, and recording one would fail every subsequent check.
    markers = {}
    for n, f in live.items():
        shots = f if isinstance(f, list) else [f]
        per_frame = [detect(s_, DEFAULT_DICTIONARY) for s_ in shots]
        if len(per_frame) >= MIN_STABILITY_FRAMES:
            markers[n] = stable_landmarks(per_frame)
            rejected = set().union(*[set(d) for d in per_frame]) - set(markers[n])
            if rejected:
                print(f"  {n}: rejected unstable detection(s) "
                      f"{sorted(rejected)} — seen in some frames only, or "
                      f"moving between them (detector phantoms)")
        else:
            markers[n] = per_frame[0] if per_frame else {}
    seen = {n: m for n, m in markers.items() if m}

    # ArUco wherever markers are visible, even to only one camera: a wrist
    # camera without them must not force the fixed camera onto a weaker method.
    if seen:
        ReferenceSet(method=ARUCO_METHOD, dictionary=DEFAULT_DICTIONARY,
                     tolerance_px=DEFAULT_TOLERANCE_PX,
                     cameras=seen).write(path)
        for name, marks in sorted(seen.items()):
            print(f"  {name:<14} ArUco, {len(marks)} landmark(s): "
                  f"{sorted(marks)}")
    else:
        # No markers in view. The scene's own texture carries the reference
        # instead; RANSAC is what keeps a moved cable from reading as drift.
        import cv2
        base = Path(path).parent
        base.mkdir(parents=True, exist_ok=True)
        cameras_grid, images = {}, {}
        for name, frame in sorted(live.items()):
            if isinstance(frame, list):
                frame = frame[0]
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            try:
                estimate_homography(gray, gray)     # can this scene be matched?
            except DriftError as exc:
                print(f"ERROR: {name}: {exc}", file=sys.stderr)
                return 1
            filename = f"calibration_reference_{name}.png"
            cv2.imwrite(str(base / filename), frame)
            h, w = gray.shape[:2]
            cameras_grid[name] = probe_grid(w, h)
            images[name] = {"file": filename,
                            "sha256": _sha256(base / filename)}
            print(f"  {name:<14} ORB homography over natural texture, "
                  f"{len(cameras_grid[name])} probe points -> {filename}")
        ReferenceSet(method=ORB_METHOD, dictionary="",
                     tolerance_px=DEFAULT_TOLERANCE_PX,
                     cameras=cameras_grid, images=images).write(path)

    if moving:
        print(f"  NOT REFERENCED: {moving} — not a fixed mount. A wrist "
              f"camera's view moves with the arm, so a reference would measure "
              f"the arm, not the mount. Needs a repeatable arm pose first")
    empty = sorted(n for n in live
                   if frames[n] is None or (seen and not markers.get(n)))
    if empty:
        print(f"  NOT REFERENCED (no landmarks/frame): {empty} — these report "
              f"as NOT CHECKED and their mounts are unguarded")
    print(f"recorded drift reference -> {path}")
    print("This redefines 'not drifted': re-record CALIBRATION_SHA256 "
          "and add an experiment-registry entry")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
