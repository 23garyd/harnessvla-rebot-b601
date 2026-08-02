"""Cross-check two independent FK solvers over the same URDF.

Once eef_pose() comes from forward kinematics rather than a sensor, the
workspace guard is trusting a computation. This is the cheapest available
check on that computation: solve the same joint vectors with placo (what
LeRobot's RobotKinematics wraps, and what B601Driver uses) and with Pinocchio
(what the vendor's own examples use), and see whether they agree.

Agreement does NOT prove the FK is right. Both solvers read the same URDF, so
a wrong URDF, a wrong end-effector frame or a wrong joint ORDER would produce
two identical wrong answers. What it does prove is that our understanding of
the model — frame name, joint ordering, units, root convention — is not
library-specific, which is the failure mode you cannot see from one solver.

The measurement that actually validates FK is Day-3 calibration: reprojection
and position error at known table points. Until that passes, eef_pose() is an
assumption the safety layer rests on, and the risk log says so.

DIAGNOSTIC, not a runtime dependency. Neither placo nor Pinocchio is imported
until you call this, so the unpowered suite does not need either.
"""
import argparse
import contextlib
import sys
from dataclasses import dataclass

# The vendor's own kinematics config, config/rebotarm_rs.yaml:
#   urdf_path: urdf/00-arm-rs_asm-v3/urdf/00-arm-rs_asm-v3.urdf
#   end_effector_frame: gripper_end
#   arm joints: joint1 .. joint6
DEFAULT_EE_FRAME = "gripper_end"
ARM_JOINTS = ("joint1", "joint2", "joint3", "joint4", "joint5", "joint6")

# The LeRobot plugin names the same six axes differently. Nothing enforces the
# correspondence below — it is the ORDER that matters to FK, and getting it
# wrong yields poses that look plausible and are wrong everywhere but home.
# Confirm it against the arm on Day 2 before trusting any of this.
LEROBOT_MOTOR_ORDER = ("shoulder_pan", "shoulder_lift", "elbow_flex",
                       "wrist_flex", "wrist_yaw", "wrist_roll")


@dataclass(frozen=True)
class Disagreement:
    q_deg: tuple
    position_m: float          # euclidean distance between the two EE origins
    placo_xyz: tuple
    pinocchio_xyz: tuple


class KinematicsCheckError(RuntimeError):
    """A solver could not be built, or the model does not match expectations."""


def model_root(urdf_path):
    """Directory the URDF's relative mesh paths resolve against.

    The vendor URDF says `filename="meshes/base_link.STL"`, which is relative
    to the description root (the parent of urdf/), not to the URDF file and
    not to the caller's cwd. placo loads meshes at construction and fails
    outright if they are missing, so this has to be right.
    """
    from pathlib import Path
    urdf_path = Path(urdf_path).resolve()
    for candidate in (urdf_path.parent, urdf_path.parent.parent):
        if (candidate / "meshes").is_dir():
            return candidate
    return urdf_path.parent


@contextlib.contextmanager
def staged_urdf(urdf_path):
    """Yield a URDF path whose relative mesh references resolve.

    placo resolves `filename="meshes/..."` against the directory holding the
    URDF FILE; the vendor ships the URDF one level down in urdf/, with the
    meshes at the description root. Loading it in place fails outright. Rather
    than editing the vendor file, stage a copy beside the meshes for the
    duration of construction. (Pinocchio builds the kinematic model without
    meshes and does not care either way.)
    """
    import shutil
    import tempfile
    from pathlib import Path
    urdf_path = Path(urdf_path).resolve()
    root = model_root(urdf_path)
    if urdf_path.parent == root:
        yield urdf_path
        return
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        for asset in ("meshes", "collision", "visual"):
            if (root / asset).is_dir():
                (tmp / asset).symlink_to(root / asset)
        staged = tmp / urdf_path.name
        shutil.copyfile(urdf_path, staged)
        yield staged


def _require(module, extra):
    try:
        return __import__(module)
    except ImportError as exc:
        raise KinematicsCheckError(
            f"{module} is not importable by {sys.executable}: {exc}. "
            f"Install it with {extra}.") from exc


def placo_fk(urdf_path, ee_frame=DEFAULT_EE_FRAME):
    """-> callable(q_deg_sequence) -> (x, y, z). Degrees in, metres out.

    Degrees because that is what LeRobot's RobotKinematics takes and what the
    Seeed plugin's observations report; keeping the boundary in one place is
    how the rad/deg trap stays shut.
    """
    placo = _require("placo", 'pip install "lerobot[kinematics]"')
    import numpy as np
    from pathlib import Path

    with staged_urdf(urdf_path) as staged:
        robot = placo.RobotWrapper(str(staged))

    def fk(q_deg):
        for name, value in zip(ARM_JOINTS, q_deg):
            robot.set_joint(name, float(np.deg2rad(value)))
        robot.update_kinematics()
        T = robot.get_T_world_frame(ee_frame)
        return (float(T[0, 3]), float(T[1, 3]), float(T[2, 3]))

    return fk


def pinocchio_fk(urdf_path, ee_frame=DEFAULT_EE_FRAME):
    """-> callable(q_deg_sequence) -> (x, y, z).

    Note forwardKinematics alone does NOT populate data.oMf; frame placements
    need updateFramePlacements. Reading oMf without it returns stale values —
    a wrong answer that looks like a right one.
    """
    pin = _require("pinocchio", "pip install pin")
    import numpy as np
    from pathlib import Path

    with staged_urdf(urdf_path) as staged:
        model = pin.buildModelFromUrdf(str(staged))
    data = model.createData()
    if not model.existFrame(ee_frame):
        raise KinematicsCheckError(
            f"{urdf_path}: no frame named {ee_frame!r}; "
            f"have {[f.name for f in model.frames]}")
    frame_id = model.getFrameId(ee_frame)
    # Map arm joints onto their slots in q; the model also carries the two
    # prismatic gripper fingers, which FK of the EE frame does not depend on.
    slots = []
    for name in ARM_JOINTS:
        if not model.existJointName(name):
            raise KinematicsCheckError(
                f"{urdf_path}: no joint named {name!r}")
        slots.append(model.idx_qs[model.getJointId(name)])

    def fk(q_deg):
        q = pin.neutral(model)
        for slot, value in zip(slots, q_deg):
            q[slot] = float(np.deg2rad(value))
        pin.forwardKinematics(model, data, q)
        pin.updateFramePlacements(model, data)
        t = data.oMf[frame_id].translation
        return (float(t[0]), float(t[1]), float(t[2]))

    return fk


def compare_fk(fk_a, fk_b, samples):
    """-> [Disagreement], one per sampled joint vector, worst first."""
    out = []
    for q_deg in samples:
        a = fk_a(q_deg)
        b = fk_b(q_deg)
        d = sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5
        out.append(Disagreement(tuple(q_deg), d, a, b))
    return sorted(out, key=lambda d: -d.position_m)


def sample_joint_vectors(n=200, span_deg=90.0, seed=0):
    """Deterministic sweep over a conservative joint range.

    Seeded so a disagreement is reproducible: "it failed on some random pose"
    is not a bug report.
    """
    import random
    rng = random.Random(seed)
    samples = [(0.0,) * len(ARM_JOINTS)]                    # zero / home
    for i in range(len(ARM_JOINTS)):                        # one axis at a time
        for value in (-span_deg, span_deg):
            q = [0.0] * len(ARM_JOINTS)
            q[i] = value
            samples.append(tuple(q))
    while len(samples) < n:
        samples.append(tuple(rng.uniform(-span_deg, span_deg)
                             for _ in ARM_JOINTS))
    return samples[:n]


def render_report(worst, tolerance_m):
    lines = [
        f"placo vs pinocchio over {len(worst)} joint vectors",
        f"  max disagreement: {worst[0].position_m:.9f} m",
        f"  mean:             "
        f"{sum(d.position_m for d in worst) / len(worst):.9f} m",
        f"  tolerance:        {tolerance_m:.9f} m",
    ]
    if worst[0].position_m > tolerance_m:
        d = worst[0]
        lines += [
            "",
            "WORST CASE",
            f"  q (deg):     {tuple(round(v, 3) for v in d.q_deg)}",
            f"  placo:       {tuple(round(v, 6) for v in d.placo_xyz)}",
            f"  pinocchio:   {tuple(round(v, 6) for v in d.pinocchio_xyz)}",
            "",
            "The two solvers disagree. Do not treat eef_pose() as usable until",
            "this is understood: check the end-effector frame name, the joint",
            "ordering, and that both are reading the same URDF.",
        ]
    else:
        lines += [
            "",
            "Solvers agree. This validates the frame name, joint ordering and",
            "units — NOT the URDF itself. Both read the same file, so a wrong",
            "model gives two identical wrong answers. Day-3 calibration is the",
            "measurement that validates FK against the actual arm.",
        ]
    return "\n".join(lines)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("urdf", help="path to the B601-RS URDF")
    p.add_argument("--ee-frame", default=DEFAULT_EE_FRAME)
    p.add_argument("--samples", type=int, default=200)
    p.add_argument("--span-deg", type=float, default=90.0)
    p.add_argument("--tolerance-m", type=float, default=1e-6,
                   help="two solvers on one model should agree to ~machine "
                        "precision; a real disagreement is a modelling error, "
                        "not numerical noise")
    args = p.parse_args(argv)

    try:
        fk_a = placo_fk(args.urdf, args.ee_frame)
        fk_b = pinocchio_fk(args.urdf, args.ee_frame)
    except KinematicsCheckError as exc:
        print(f"KINEMATICS CHECK UNAVAILABLE: {exc}", file=sys.stderr)
        return 2

    worst = compare_fk(fk_a, fk_b,
                       sample_joint_vectors(args.samples, args.span_deg))
    print(render_report(worst, args.tolerance_m))
    return 0 if worst[0].position_m <= args.tolerance_m else 1


if __name__ == "__main__":
    sys.exit(main())
