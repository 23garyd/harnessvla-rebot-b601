# B601 safety-boundary fixes — design

**Date:** 2026-07-31  
**Repository:** `harnessvla-rebot-b601` only  
**Scope:** Unpowered scaffold behavior. No hardware access or robot motion.

## Goal

Close the confirmed safety-boundary gaps before planner-controlled powered
motion:

1. A raw-driver actuation failure must leave `SafeDriver` faulted and block
   later actuation until a human explicitly clears the fault.
2. Cartesian move speed must be finite, positive, and at or below the
   configured maximum.
3. Homing must have an explicit bounded contract rather than an unchecked raw
   pass-through or a misleading reuse of the normal Cartesian step check.
4. Experiment pin checks must use this repository's `.venv` interpreter.

The HarnessVLA paper motivates the fixed primitive boundary and returning
control after each primitive. The real-robot safety requirements come from the
B601 plan: code-enforced limits, bounded primitives, explicit status/failure
paths, and no unsafe continuation.

## Non-goals

- Implementing the B601 vendor driver.
- Claiming a safe physical homing trajectory before vendor bring-up and mentor
  review.
- Adding planner, ACT, perception, or retry behavior.
- Changing the completed simulation repository
  `/home/demo/github_sow_harnessVLA`.
- Changing the experiment's provisional numerical safety limits.

## Design decisions

### 1. One fail-closed raw-motion boundary

`SafeDriver` will use a small internal helper for raw actuation calls. If the
raw driver raises any `Exception`, the helper records a diagnostic fault
containing the operation and exception, then re-raises the original exception.
Subsequent `move_to`, `set_gripper`, or `safe_home` calls continue to be
rejected by `_require_ok()` until `clear_fault()` is called.

`disable()` remains callable while faulted. This is deliberate: a fault must
never prevent the action used to make hardware quiescent.

This helper will cover `move_to`, `set_gripper`, and `safe_home`; otherwise the
same bug would survive on another actuation path.

### 2. Explicit speed validation

A pure `check_cartesian_speed(speed, limits)` guard will reject:

- non-numeric values, including booleans;
- NaN and infinity;
- zero and negative values;
- values above `max_cartesian_speed`.

`SafeDriver.move_to()` will run this guard before reading robot state or
forwarding a command. A rejected speed latches a `SafetyViolation`, matching
other rejected motion commands.

### 3. Homing is a separate bounded contract

Ordinary `check_command()` is not sufficient for homing: its Cartesian
per-waypoint distance check cannot prove that a joint-space homing trajectory
is safe and may reject a legitimate long homing route.

The abstract `Driver.safe_home` contract will therefore accept two mandatory
bounds:

- `max_joint_velocity`
- `timeout_s`

`SafeDriver.safe_home(timeout_s=...)` will:

1. require a clear fault state;
2. validate that timeout is finite and positive;
3. validate current joint velocities and current end-effector pose;
4. call the raw driver's bounded homing operation with the configured maximum
   joint velocity and requested timeout through the fail-closed helper;
5. validate the returned end-effector pose and joint velocities;
6. increment the audited motion count only after the postconditions pass.

The eventual B601 vendor implementation is responsible for executing the
mentor-approved joint-space route, enforcing the supplied velocity limit and
timeout internally, and stopping on failure. Until that implementation exists,
the interface and mock tests make the obligation explicit without pretending
that a Cartesian endpoint check guarantees trajectory safety.

The default homing timeout will be conservative and code-local for the
unpowered scaffold. It must move into reviewed robot configuration during
Day-2 vendor bring-up before powered homing.

### 4. Repository interpreter is unambiguous

`pin_check.sh` will always execute probes with
`$REPO/.venv/bin/python`. The unrestricted `B601_PY` override will be removed
from the pin gate and from its documentation.

`setup.sh` will rename its bootstrap interpreter override to
`B601_BOOTSTRAP_PY`. That interpreter is used only to create `.venv`; it is not
the interpreter whose packages are experiment-pinned. This avoids one
environment variable having two incompatible meanings.

If the robot PC later requires a managed Conda environment, adopting it will be
an explicit design/protocol change with a recorded environment manifest, not a
silent pin-gate override.

## Error behavior

- Guard rejection: raise `SafetyViolation`, latch its reason, send no raw
  command.
- Raw-driver exception: latch operation plus exception details, re-raise the
  original exception, send no later command until explicit clear.
- Homing precondition or postcondition failure: latch `SafetyViolation`.
- Disable failure: propagate the raw exception; do not block the attempt based
  on the existing fault state.
- Missing repository interpreter: fail with the existing actionable setup
  message.

## Test strategy

All tests remain unpowered and use `MockDriver`.

TDD regression tests will first demonstrate:

1. a raw move failure latches a fault and blocks the next move;
2. raw gripper and homing failures also latch faults;
3. negative, zero, NaN, infinity, boolean, and non-numeric speeds never reach
   the raw driver;
4. bounded valid speed still reaches the driver;
5. homing forwards the configured joint-velocity cap and timeout;
6. homing rejects invalid timeout and invalid pre/post state;
7. successful homing increments the motion audit count;
8. `pin_check.sh` ignores/rejects an ambient `B601_PY` and uses the repository
   interpreter;
9. `setup.sh` accepts `B601_BOOTSTRAP_PY` solely for environment creation;
10. README commands refer only to the repository environment.

Each regression test must be observed failing for the intended reason before
production code changes. Completion requires the focused tests, the complete
unpowered suite, shell syntax checks, and a read-only code review.

## Acceptance criteria

- No invalid speed reaches `MockDriver`.
- Any raw actuation failure leaves `SafeDriver.faulted` non-empty.
- A second actuation after a fault is rejected until explicit clearance.
- Homing has enforced preconditions, passed-through bounds, checked
  postconditions, and auditable motion accounting.
- Pin probes cannot be redirected to an ambient interpreter.
- The complete unpowered test suite passes.
- Git changes are confined to `/home/demo/github_b601_harnessVLA`.
