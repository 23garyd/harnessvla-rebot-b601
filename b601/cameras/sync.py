"""Did the cameras actually deliver one synchronised observation stream?

`b601.cameras.config` refuses a manifest whose cameras disagree on frame rate.
That checks INTENT. This checks DELIVERY, which on this machine is a different
question: two cameras share one host, the D405 negotiated USB 2.1, and a sensor
that accepted a 30 fps request is under no obligation to honour it.

Why it is worth a module. The wrist camera is the only sensor that can verify a
grasp (sim finding 4) and the fixed camera is what the planner re-grounds from
(finding 1). If an observation's two images are of different instants,
verification and scene estimate disagree about where the arm was, while the
dataset records them as one observation. Nothing downstream can detect that, and
120-200 teleop episodes cannot be re-recorded.

WHAT THE HARDWARE ACTUALLY DID, measured on epyc 2026-08-06 over 150 frames per
camera at 640x480/30, and the reason this module's first model was WRONG:

    agentview (UVC)     mean interval 33.02 ms   jitter p95 3.12 ms   0 dropped
    eye_in_hand (D405)  mean interval 33.30 ms   jitter p95 0.22 ms   0 dropped

Both within a whisker of 30 fps, and 0.28 ms/frame apart in rate. Compared frame
index against frame index that accumulates without bound — 76 ms after 150
frames, more in a longer episode — and the first version of this checker called
a healthy pair of cameras misaligned. Two USB cameras with no hardware sync
ALWAYS drift; the mistake was the pairing model, not the hardware.

So the verdict is computed the way a recorder assembles an observation: pair each
frame with the NEAREST frame in the other stream by timestamp. Under that model
the same recording sat at a 9.0 ms p95 gap, 0.27 of a frame period. The
consequence for the recording pipeline is a requirement, not a preference:
**pair frames by timestamp, never by frame index.**

Two further corrections the same measurement forced. Jitter is bounded on its
p95, not its max, because every V4L2 capture starts by flushing buffered frames
(the first two intervals here were 6.0 and 13.6 ms, against 3.12 ms p95 for the
rest) and a max-based bound is hostage to that artifact. And frames outside the
window every stream covers are excluded and counted, because equal frame counts
at unequal rates leave the slower stream running past the other's last frame.

Pure by construction, like `limits.py`: timestamps in, report out. No cameras,
no filesystem, no clock. That is what lets it run in CI with the arm unpowered,
and it is also the boundary of what it can know.

WHAT THIS DOES NOT COVER, stated here rather than discovered in week three:

  - It reads TIMESTAMPS, NOT IMAGES. If the recorder stamps host arrival time
    rather than sensor capture time, USB buffering moves the number without
    moving the exposure instant. Perfectly aligned arrival stamps can mean
    misaligned pictures, and this cannot see the difference.
  - A CONSTANT latency difference between two cameras is invisible for the same
    reason. If camera A is always stamped 15 ms late, the streams look aligned
    to each other while both are wrong about when the arm was where. Only a
    physical event visible to both cameras measures that.
  - Worse, nearest-timestamp pairing ALIASES any constant offset into at most
    half a frame period: with free-running cameras, "20 ms late" and "13 ms
    early on the next frame" are the same sequence of arrival times. So a
    constant skew is not merely unmeasured here, it is unmeasurable from
    timestamps alone, and passing this check is not evidence against one.
  - It says nothing about CONTENT. A frozen camera re-delivering one frame with
    immaculate timestamps passes every check here.
  - It does not know the frames correspond to the recorded joint state or
    action. Aligning the cameras to each other is not aligning them to the arm.
  - `dropped` is inferred from interval arithmetic, not from sequence numbers.
    A camera that silently repeats a frame instead of dropping it looks clean.
"""
import bisect
import math
from dataclasses import dataclass

# Nearest-timestamp pairing between free-running cameras is bounded by half a
# frame period by construction, so the bound sits just above that: it exists to
# catch a STALL, where a stream leaves observations with no contemporaneous
# frame at all, not to re-measure the structural half-period.
DEFAULT_OFFSET_TOLERANCE_FRAMES = 0.6
# Tighter than half a frame, and measured: the UVC camera's real steady-state
# jitter was 3 ms (0.09 of a period). A bound of half a period is unreachable
# without the interval also rounding to two frames, i.e. being counted as a
# drop — so it would never fire on its own.
DEFAULT_JITTER_TOLERANCE_FRAMES = 0.25
# A rate error is systematic and accumulates over an episode where jitter
# averages out. 1/22 against a requested 1/30 is only 0.36 of a frame per
# interval while being a stream running at three quarters of the intended rate.
DEFAULT_RATE_TOLERANCE_FRAMES = 0.25


class SyncError(Exception):
    """The timestamps could not be checked. Never swallow this."""


@dataclass(frozen=True)
class StreamReport:
    """Measurements for one stream. Carries no verdict — thresholds live in
    check_sync, so the numbers can be read without agreeing with the bounds."""
    name: str
    frames: int
    expected_interval_s: float
    mean_interval_s: float
    min_interval_s: float
    max_interval_s: float
    max_jitter_s: float
    jitter_p95_s: float
    dropped: int

    @property
    def rate_error_frames(self):
        """Signed mean-interval error, in frame periods. Positive is slow."""
        return (self.mean_interval_s - self.expected_interval_s) \
            / self.expected_interval_s


@dataclass(frozen=True)
class SyncReport:
    streams: tuple
    frame_counts: dict
    # Verdict metric: nearest-timestamp pairing, which is how a recorder builds
    # an observation. Bounded by half a frame period for healthy free-running
    # cameras, so it fires on stalls.
    pair_gap_p95_s: float
    pair_gap_max_s: float
    # How many frame pairings were actually computed. Zero across two or more
    # streams means they share no common window, so the pairing metric is
    # undefined -- it must not read as a perfect score.
    pairs_compared: int
    # Frames outside the window every stream covers, excluded from the pairing
    # metric. Counted rather than dropped quietly.
    unpaired_frames: int
    # Diagnostics only. Index pairing is NOT a valid observation model for
    # free-running cameras, and these two numbers are what say so out loud.
    max_index_offset_s: float
    drift_s_per_frame: float
    expected_interval_s: float
    offset_tolerance_s: float
    jitter_tolerance_s: float
    rate_tolerance_frames: float

    @property
    def reasons(self):
        """Every reason this failed, not the first one found. A run with three
        problems that reports one gets fixed once and re-run twice."""
        out = []
        if len(set(self.frame_counts.values())) > 1:
            out.append(
                f"frame count mismatch {self.frame_counts} — the streams "
                f"cannot be zipped into observations")
        if len(self.streams) > 1 and self.pairs_compared == 0:
            # FOUND ON HARDWARE: preflight grabbed the cameras sequentially, so
            # the streams were 4.2 s apart and shared no overlap. Every frame
            # was excluded from pairing, the gap list held only its seed, and
            # this reported 0.00 ms and PASSED -- a perfect score for comparing
            # nothing.
            out.append(
                f"the streams do not overlap in time, so no frames could be "
                f"paired and the alignment was never measured — capture the "
                f"cameras CONCURRENTLY, not one after the other")
        elif self.pair_gap_p95_s > self.offset_tolerance_s:
            out.append(
                f"nearest-frame pairing gap p95 "
                f"{self.pair_gap_p95_s * 1e3:.1f} ms exceeds "
                f"{self.offset_tolerance_s * 1e3:.1f} ms — observations have no "
                f"contemporaneous frame in every stream")
        for s in self.streams:
            if s.dropped:
                out.append(f"{s.name}: {s.dropped} dropped frame(s)")
            if s.jitter_p95_s > self.jitter_tolerance_s:
                out.append(
                    f"{s.name}: jitter p95 {s.jitter_p95_s * 1e3:.1f} ms "
                    f"exceeds {self.jitter_tolerance_s * 1e3:.1f} ms")
            if abs(s.rate_error_frames) > self.rate_tolerance_frames:
                out.append(
                    f"{s.name}: delivered rate {1 / s.mean_interval_s:.2f} fps "
                    f"against {1 / self.expected_interval_s:.2f} requested")
        return tuple(out)

    @property
    def passed(self):
        return not self.reasons

    def summary(self):
        head = "SYNC OK" if self.passed else "SYNC FAILED"
        lines = [f"{head}  ({len(self.streams)} stream(s), "
                 f"{1 / self.expected_interval_s:.2f} fps requested)"]
        for s in self.streams:
            lines.append(
                f"  {s.name:<14} {s.frames:>5} frames  "
                f"mean {s.mean_interval_s * 1e3:7.2f} ms  "
                f"jitter p95 {s.jitter_p95_s * 1e3:6.2f} ms "
                f"(max {s.max_jitter_s * 1e3:6.2f})  dropped {s.dropped}")
        lines.append(
            f"  pairing gap (nearest timestamp)  p95 "
            f"{self.pair_gap_p95_s * 1e3:6.2f} ms  max "
            f"{self.pair_gap_max_s * 1e3:6.2f} ms   <- the verdict metric")
        lines.append(
            f"  {self.unpaired_frames} frame(s) outside the common window, "
            f"excluded from pairing (unpaired: capture start/stop, not sync)")
        lines.append(
            f"  index-paired offset {self.max_index_offset_s * 1e3:.2f} ms, "
            f"drift {self.drift_s_per_frame * 1e3:+.3f} ms/frame — diagnostic "
            f"only: free-running cameras always drift, so the recorder MUST "
            f"pair frames by timestamp, never by frame index")
        for reason in self.reasons:
            lines.append(f"  FAIL: {reason}")
        return "\n".join(lines)


def _period(fps):
    if isinstance(fps, bool) or not isinstance(fps, (int, float)):
        raise SyncError(f"fps must be a number, got {fps!r}")
    if not math.isfinite(fps) or fps <= 0:
        raise SyncError(f"fps must be positive and finite, got {fps!r}")
    return 1.0 / float(fps)


def _validated(name, timestamps):
    ts = list(timestamps)
    if len(ts) < 2:
        raise SyncError(
            f"{name}: need at least two timestamps to measure an interval, "
            f"got {len(ts)}")
    for i, t in enumerate(ts):
        if isinstance(t, bool) or not isinstance(t, (int, float)):
            raise SyncError(f"{name}: timestamp {i} is not a number: {t!r}")
        if not math.isfinite(t):
            # NaN passes every naive comparison, as the safety layer documents,
            # including the monotonicity test immediately below.
            raise SyncError(f"{name}: timestamp {i} is not finite: {t!r}")
    for i in range(1, len(ts)):
        if ts[i] <= ts[i - 1]:
            # Sorting here would manufacture a clean stream from a broken
            # recorder, and duplicate stamps cannot both be an instant.
            raise SyncError(
                f"{name}: timestamps are not strictly monotonic at index {i} "
                f"({ts[i - 1]!r} then {ts[i]!r})")
    return ts


def _p95(values):
    """Nearest-rank 95th percentile. Deliberately not a mean: the measured UVC
    capture's worst interval came from buffered frames flushing at stream
    start, and a mean would dilute a genuine stall instead of surfacing it."""
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(0.95 * len(ordered)) - 1))
    return ordered[index]


def check_stream(name, timestamps, fps):
    """-> StreamReport. Measures one stream against its requested rate."""
    period = _period(fps)
    ts = _validated(name, timestamps)
    intervals = [b - a for a, b in zip(ts, ts[1:])]

    # Count MISSING FRAMES, not gaps: five frame periods of silence is four
    # absent frames, and reporting it as one event under-reports a USB stall.
    dropped = 0
    for d in intervals:
        missing = int(round(d / period)) - 1
        if missing > 0:
            dropped += missing

    return StreamReport(
        name=name,
        frames=len(ts),
        expected_interval_s=period,
        mean_interval_s=sum(intervals) / len(intervals),
        min_interval_s=min(intervals),
        max_interval_s=max(intervals),
        max_jitter_s=max(abs(d - period) for d in intervals),
        jitter_p95_s=_p95([abs(d - period) for d in intervals]),
        dropped=dropped,
    )


def check_sync(streams, fps,
               offset_tolerance_frames=DEFAULT_OFFSET_TOLERANCE_FRAMES,
               jitter_tolerance_frames=DEFAULT_JITTER_TOLERANCE_FRAMES,
               rate_tolerance_frames=DEFAULT_RATE_TOLERANCE_FRAMES):
    """-> SyncReport for a mapping of stream name -> timestamp sequence.

    `streams` may hold a single entry: rate and drops are still worth checking
    with one camera, there is simply nothing for it to be misaligned with.
    """
    period = _period(fps)
    if not streams:
        raise SyncError("no streams to check")

    reports = tuple(check_stream(name, ts, fps)
                    for name, ts in sorted(streams.items()))
    validated = {name: _validated(name, ts) for name, ts in streams.items()}

    # Index-against-index, kept as a DIAGNOSTIC only. Measured on this machine:
    # two healthy cameras 0.28 ms/frame apart in rate reached 76 ms of
    # index-paired offset in 150 frames and would reach more in a longer
    # episode. Failing on it would condemn hardware that is working.
    shortest = min(len(ts) for ts in validated.values())
    max_index_offset = 0.0
    for i in range(shortest):
        at_i = [ts[i] for ts in validated.values()]
        max_index_offset = max(max_index_offset, max(at_i) - min(at_i))
    means = [s.mean_interval_s for s in reports]
    drift = max(means) - min(means)

    # THE VERDICT METRIC: pair each frame with the nearest frame in every other
    # stream, which is what a recorder does when it assembles an observation.
    # Bounded by half a frame period whenever every stream is delivering, so
    # what it actually detects is a stall — an observation with no
    # contemporaneous frame available.
    # Only inside the window every stream actually covers. Outside it a frame
    # has no counterpart because capture started or stopped, not because the
    # cameras disagreed: measured, 150 frames from each of two cameras at
    # slightly different rates left the slower one running past the other's last
    # frame and reported a 69.8 ms gap on a healthy recording. Excluded frames
    # are COUNTED, because a metric that quietly drops samples reads as
    # coverage it does not have.
    window_start = max(ts[0] for ts in validated.values())
    window_end = min(ts[-1] for ts in validated.values())
    gaps = [0.0]
    unpaired = 0
    others = list(validated.items())
    for name, ts in others:
        for other_name, other in others:
            if other_name == name:
                continue
            for t in ts:
                if not window_start <= t <= window_end:
                    unpaired += 1
                    continue
                j = bisect.bisect_left(other, t)
                near = [other[k] for k in (j - 1, j) if 0 <= k < len(other)]
                if near:
                    gaps.append(min(abs(t - c) for c in near))

    return SyncReport(
        streams=reports,
        frame_counts={name: len(ts) for name, ts in sorted(validated.items())},
        pair_gap_p95_s=_p95(gaps),
        pair_gap_max_s=max(gaps),
        pairs_compared=len(gaps) - 1,          # the seed is not a pairing

        unpaired_frames=unpaired,
        max_index_offset_s=max_index_offset,
        drift_s_per_frame=drift,
        expected_interval_s=period,
        offset_tolerance_s=offset_tolerance_frames * period,
        jitter_tolerance_s=jitter_tolerance_frames * period,
        rate_tolerance_frames=rate_tolerance_frames,
    )


def main(argv=None):
    """`python -m b601.cameras.sync <timestamps.json>` — check a recording.

    Input is `{"streams": {"<name>": [t, ...], ...}}` with an optional "fps".
    When "fps" is absent the manifest's declared rate is used: a rate retyped
    into the recording is a rate that can disagree with the one the cameras
    were configured from, the same reason `URDF_EE_FRAME` is read from the
    driver rather than written into the pin a second time.

    Exit status is the point — 0 clean, 1 not, so a recording session can be
    gated on it instead of the report being read by eye. A recording that
    cannot be INTERPRETED (non-monotonic stamps, missing keys) is also 1, but
    reported on stderr as an error rather than as a failed check: "the cameras
    were misaligned" and "this file is not a recording" must not read alike.
    """
    import json
    import sys
    from pathlib import Path

    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 1:
        print("usage: python -m b601.cameras.sync <timestamps.json>",
              file=sys.stderr)
        return 64

    path = Path(argv[0])
    if not path.is_file():
        print(f"ERROR: recording not found: {path}", file=sys.stderr)
        return 1
    try:
        raw = json.loads(path.read_text())
    except ValueError as exc:
        print(f"ERROR: {path}: not valid JSON: {exc}", file=sys.stderr)
        return 1
    if not isinstance(raw, dict) or not isinstance(raw.get("streams"), dict) \
            or not raw["streams"]:
        print(f"ERROR: {path}: no 'streams' mapping to check", file=sys.stderr)
        return 1

    fps = raw.get("fps")
    if fps is None:
        # Imported here, not at module scope: this module is pure and must stay
        # importable without a manifest on disk.
        from b601.cameras.config import (CameraManifestError, load_cameras,
                                         record_fps)
        try:
            fps = record_fps(load_cameras())
        except CameraManifestError as exc:
            print(f"ERROR: no 'fps' in {path} and the camera manifest could "
                  f"not supply one: {exc}", file=sys.stderr)
            return 1

    try:
        report = check_sync(raw["streams"], fps)
    except SyncError as exc:
        print(f"ERROR: {path}: {exc}", file=sys.stderr)
        return 1

    print(report.summary())
    return 0 if report.passed else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
