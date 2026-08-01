"""Five-pose repeatability harness — the Day-2 evidence producer.

The plan's Day-2 gate: twenty consecutive low-speed motions with no fault,
collision, or manual correction, evidenced by commanded vs achieved state,
error, duration and faults. Five poses x four cycles is those twenty motions.

Everything here goes through a SafeDriver. There is no path from this module
to a raw driver, so a repeatability run cannot be the thing that moves the arm
somewhere the envelope forbids.

TWO REFUSALS, both deliberate:

  It stops at the first fault. SafeDriver latches, so every later motion would
  be refused anyway — but more importantly, twenty motions counted across a
  fault is not the quantity the gate names. The run reports how many
  CONSECUTIVE clean motions it achieved, which is the number that matters.

  It cannot pass the gate by itself. Collisions and manual corrections are
  human observations; nothing here perceives them. gate_status() requires an
  explicit operator attestation, so a green run can never be mistaken for a
  gate that someone actually watched.

UNVERIFIED ON HARDWARE. Written and tested against MockDriver so that on
bring-up day the arm is the only new variable — not this code.
"""
import argparse
import csv
import statistics
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from b601.safety.limits import SafetyViolation

# Conservative, mutually close poses inside the shipped envelope: the harness
# measures repeatability, not the step-distance guard. Day 2 may replace these
# with poses chosen against the real table, via --poses.
DEFAULT_POSES = [
    (0.30, 0.00, 0.35),
    (0.34, 0.04, 0.33),
    (0.28, -0.04, 0.37),
    (0.33, -0.02, 0.31),
    (0.31, 0.03, 0.39),
]

GATE_MOTIONS = 20


@dataclass(frozen=True)
class Trial:
    pose_id: int
    cycle: int
    commanded: tuple
    achieved: tuple            # () when the motion never happened
    error_m: float             # nan when there is nothing to compare
    error_xyz: tuple
    duration_s: float
    speed: float
    fault: str = None


@dataclass
class RepeatabilityRun:
    poses: list
    cycles: int
    speed: float
    trials: list = field(default_factory=list)
    completed: bool = False

    @property
    def consecutive_ok(self):
        """Clean motions before the first fault — the gate's quantity."""
        n = 0
        for t in self.trials:
            if t.fault is not None:
                break
            n += 1
        return n

    @property
    def faults(self):
        return [t for t in self.trials if t.fault is not None]

    def summary(self):
        """Per-pose statistics. Per POSE, because one bad pose is the finding
        and a global mean buries it."""
        out = {}
        for t in self.trials:
            if t.fault is not None:
                continue
            out.setdefault(t.pose_id, []).append(t.error_m)
        return {
            pose_id: {
                "n": len(errors),
                "mean_error_m": statistics.fmean(errors),
                "max_error_m": max(errors),
                "stdev_error_m": (statistics.stdev(errors)
                                  if len(errors) > 1 else 0.0),
            }
            for pose_id, errors in sorted(out.items())
        }

    def errors(self):
        return [t.error_m for t in self.trials if t.fault is None]


@dataclass(frozen=True)
class GateStatus:
    passed: bool
    reason: str


def run_repeatability(safe_driver, poses=None, cycles=4, speed=None,
                      settle_s=0.0, clock=time.perf_counter,
                      before_move=None):
    """Drive `poses` for `cycles` rounds through `safe_driver`, recording each
    motion. Stops at the first fault. Returns a RepeatabilityRun.

    `before_move` is a test seam (called with the 0-based motion index); the
    CLI never passes it.
    """
    poses = list(DEFAULT_POSES if poses is None else poses)
    speed = safe_driver.limits.max_cartesian_speed if speed is None else speed
    run = RepeatabilityRun(poses=poses, cycles=cycles, speed=speed)

    index = 0
    for cycle in range(1, cycles + 1):
        for pose_id, pose in enumerate(poses, start=1):
            if before_move is not None:
                before_move(index)
            index += 1
            started = clock()
            fault = None
            achieved = ()
            try:
                safe_driver.move_to(pose, speed=speed)
                achieved = tuple(safe_driver.eef_pose())
            except SafetyViolation as exc:
                fault = f"SafetyViolation: {exc}"
            except Exception as exc:            # driver/hardware failure
                fault = f"{type(exc).__name__}: {exc}"
            duration = clock() - started

            if fault is None:
                error_xyz = tuple(a - b for a, b in zip(achieved, pose))
                error_m = sum(e * e for e in error_xyz) ** 0.5
            else:
                error_xyz = ()
                error_m = float("nan")

            run.trials.append(Trial(
                pose_id=pose_id, cycle=cycle, commanded=tuple(pose),
                achieved=achieved, error_m=error_m, error_xyz=error_xyz,
                duration_s=duration, speed=speed, fault=fault))

            if fault is not None:
                return run
            if settle_s:
                time.sleep(settle_s)

    run.completed = True
    return run


def gate_status(run, operator_confirmed=False):
    """The Day-2 gate: twenty consecutive clean motions AND a human saying
    there was no collision or manual correction.

    The attestation is not a formality. Nothing in this process can see the
    robot, so without it the software would be certifying a claim it has no
    way to evaluate.
    """
    if run.consecutive_ok < GATE_MOTIONS:
        return GateStatus(False, (
            f"{run.consecutive_ok} consecutive clean motions, "
            f"{GATE_MOTIONS} required"
            + (f" (stopped by: {run.faults[0].fault})" if run.faults else "")))
    if not operator_confirmed:
        return GateStatus(False, (
            f"{run.consecutive_ok} clean motions recorded, but the operator "
            "has not confirmed no collision and no manual correction — "
            "this process cannot observe either"))
    return GateStatus(True, (
        f"{run.consecutive_ok} consecutive clean motions, operator confirmed "
        "no collision and no manual correction"))


def error_histogram(errors, bins=10):
    """-> [(low, high, count)]. Text-renderable, no plotting dependency."""
    errors = [e for e in errors if e == e]          # drop NaN
    if not errors:
        return []
    lo, hi = min(errors), max(errors)
    if hi == lo:
        return [(lo, hi, len(errors))]
    width = (hi - lo) / bins
    counts = [0] * bins
    for e in errors:
        idx = min(int((e - lo) / width), bins - 1)
        counts[idx] += 1
    return [(lo + i * width, lo + (i + 1) * width, counts[i])
            for i in range(bins)]


CSV_COLUMNS = [
    "pose_id", "cycle", "cmd_x", "cmd_y", "cmd_z",
    "achieved_x", "achieved_y", "achieved_z",
    "error_m", "error_x", "error_y", "error_z",
    "duration_s", "speed", "fault",
]


def write_csv(run, out_path):
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for t in run.trials:
            cmd = t.commanded
            ach = t.achieved or ("", "", "")
            err = t.error_xyz or ("", "", "")
            writer.writerow({
                "pose_id": t.pose_id, "cycle": t.cycle,
                "cmd_x": cmd[0], "cmd_y": cmd[1], "cmd_z": cmd[2],
                "achieved_x": ach[0], "achieved_y": ach[1], "achieved_z": ach[2],
                "error_m": "" if t.error_m != t.error_m else t.error_m,
                "error_x": err[0], "error_y": err[1], "error_z": err[2],
                "duration_s": t.duration_s, "speed": t.speed,
                "fault": t.fault or "",
            })
    return out_path


def render_report(run, gate):
    lines = [
        f"repeatability: {len(run.trials)} motions, "
        f"{run.consecutive_ok} consecutive clean, "
        f"{'completed' if run.completed else 'STOPPED EARLY'}",
        "",
        "| pose | n | mean error (m) | max error (m) | stdev (m) |",
        "|---|---|---|---|---|",
    ]
    for pose_id, s in run.summary().items():
        lines.append(f"| {pose_id} | {s['n']} | {s['mean_error_m']:.5f} "
                     f"| {s['max_error_m']:.5f} | {s['stdev_error_m']:.5f} |")
    lines.append("")
    lines.append("error distribution:")
    for low, high, count in error_histogram(run.errors()):
        lines.append(f"  [{low:.5f}, {high:.5f})  {'#' * count} {count}")
    if run.faults:
        lines.append("")
        lines.append(f"FAULT: {run.faults[0].fault}")
    lines.append("")
    lines.append(f"Day-2 gate: {'PASS' if gate.passed else 'NOT PASSED'} — "
                 f"{gate.reason}")
    return "\n".join(lines)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cycles", type=int, default=4)
    p.add_argument("--speed", type=float, default=None,
                   help="m/s; defaults to the envelope's max_cartesian_speed")
    p.add_argument("--settle", type=float, default=0.5,
                   help="seconds to hold at each pose")
    p.add_argument("--out", default="artifacts/day2/repeatability.csv")
    p.add_argument("--mock", action="store_true",
                   help="dry run against MockDriver; no hardware is touched")
    p.add_argument("--operator-confirmed", action="store_true",
                   help="attest that you watched the run and saw no collision "
                        "and no manual correction. Only a human may pass this.")
    args = p.parse_args(argv)

    from b601.driver.base import SafeDriver
    from b601.safety.config import load_home, load_limits

    workspace, limits = load_limits()
    home = load_home()
    if args.mock:
        from b601.driver.mock import MockDriver
        raw = MockDriver()
    else:
        print("no hardware driver is available yet (b601/driver/b601.py is a "
              "Day-2 deliverable); re-run with --mock for a dry run",
              file=sys.stderr)
        return 2

    sd = SafeDriver(raw, workspace, limits, home)
    run = run_repeatability(sd, cycles=args.cycles, speed=args.speed,
                            settle_s=args.settle)
    write_csv(run, args.out)
    gate = gate_status(run, operator_confirmed=args.operator_confirmed)
    print(render_report(run, gate))
    print(f"\nlog -> {args.out}")
    return 0 if gate.passed else 1


if __name__ == "__main__":
    sys.exit(main())
