# B601 Safety-Boundary Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make B601 actuation fail closed, reject invalid Cartesian speeds, expose homing as a separately bounded operation, and ensure experiment pins always inspect the repository environment.

**Architecture:** Pure validation remains in `b601/safety/limits.py`; `SafeDriver` owns fault latching and delegates already-validated operations to the raw driver. Homing remains distinct from ordinary Cartesian moves and passes explicit joint-velocity and timeout bounds to the driver. Setup uses an ambient interpreter only to create `.venv`; pin probes always use `.venv/bin/python`.

**Tech Stack:** Python 3.10, pytest, Bash, existing `MockDriver`.

## Global Constraints

- Modify only `/home/demo/github_b601_harnessVLA`; never modify `/home/demo/github_sow_harnessVLA`.
- Perform no hardware access, robot enable, CAN writes, camera access, or physical motion.
- Keep `disable()` callable while faulted.
- Do not claim that the mock proves the eventual vendor homing trajectory safe.
- Do not change provisional numerical values in `b601/setup/limits.yaml`.
- Every production behavior change requires a test observed failing for the intended reason first.

---

## File map

- `b601/safety/limits.py`: pure finite/positive scalar guards.
- `b601/driver/base.py`: abstract driver contract and `SafeDriver` fault boundary.
- `b601/driver/mock.py`: unpowered actuation recording and injected failure behavior.
- `b601/tests/test_safety.py`: regression tests for speed, raw failures, and homing.
- `b601/setup/setup.sh`: environment-bootstrap interpreter naming.
- `b601/setup/pin_check.sh`: repository-interpreter-only pin probes.
- `b601/tests/test_setup_pins.py`: regression test that ambient override cannot redirect probes.
- `README.md`: operator-facing environment contract.

---

### Task 1: Reject invalid Cartesian speeds

**Files:**
- Modify: `b601/safety/limits.py`
- Modify: `b601/driver/base.py`
- Test: `b601/tests/test_safety.py`

**Interfaces:**
- Produces: `check_cartesian_speed(speed, limits) -> float`
- Consumes: existing `MotionLimits` and `SafetyViolation`

- [ ] **Step 1: Add failing pure-guard and driver-boundary tests**

Add the import and tests:

```python
from b601.safety.limits import check_cartesian_speed


@pytest.mark.parametrize("speed", [
    -0.01, 0.0, float("nan"), float("inf"), True, "fast",
])
def test_invalid_cartesian_speed_is_rejected(speed):
    with pytest.raises(SafetyViolation, match="cartesian speed"):
        check_cartesian_speed(speed, LIM)


@pytest.mark.parametrize("speed", [
    -0.01, 0.0, float("nan"), float("inf"), True, "fast",
])
def test_invalid_speed_never_reaches_driver(speed):
    mock, sd = safe()
    with pytest.raises(SafetyViolation, match="cartesian speed"):
        sd.move_to((0.32, 0.0, 0.35), speed=speed)
    assert mock.last("move_to") is None
    assert sd.faulted is not None


def test_valid_cartesian_speed_is_normalized_and_forwarded():
    mock, sd = safe()
    sd.move_to((0.32, 0.0, 0.35), speed=0.10)
    assert mock.last("move_to")[2] == pytest.approx(0.10)
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
PYTHONPATH= .venv/bin/python -m pytest b601/tests/test_safety.py \
  -q -k 'cartesian_speed or invalid_speed'
```

Expected: collection fails because `check_cartesian_speed` does not exist.

- [ ] **Step 3: Implement the pure speed guard**

In `b601/safety/limits.py`, import `math` and `numbers`, then add:

```python
def check_cartesian_speed(speed, limits):
    if (isinstance(speed, bool)
            or not isinstance(speed, numbers.Real)
            or not math.isfinite(speed)
            or speed <= 0.0
            or speed > limits.max_cartesian_speed):
        raise SafetyViolation(
            "cartesian speed out of range",
            f"{speed!r} not finite and in (0, {limits.max_cartesian_speed}]")
    return float(speed)
```

- [ ] **Step 4: Route `SafeDriver.move_to` through the guard**

Import `check_cartesian_speed` in `b601/driver/base.py`. Put speed validation
inside the same `try/except SafetyViolation` block as `check_command`:

```python
try:
    speed = check_cartesian_speed(speed, self.limits)
    distance = check_command(
        self._d.eef_pose(), xyz, self.workspace, self.limits,
        joint_velocities=self._d.joint_state().get("velocities"))
except SafetyViolation as exc:
    self._faulted = exc.reason
    raise
```

Remove the old upper-bound-only branch.

- [ ] **Step 5: Run focused and safety tests and verify GREEN**

Run:

```bash
PYTHONPATH= .venv/bin/python -m pytest b601/tests/test_safety.py -q
```

Expected: all `test_safety.py` tests pass.

- [ ] **Step 6: Commit**

```bash
git add b601/safety/limits.py b601/driver/base.py b601/tests/test_safety.py
git commit -m "fix: reject invalid B601 Cartesian speeds"
```

---

### Task 2: Latch raw actuation failures

**Files:**
- Modify: `b601/driver/base.py`
- Modify: `b601/driver/mock.py`
- Test: `b601/tests/test_safety.py`

**Interfaces:**
- Produces: `SafeDriver._actuate(operation, function, *args)`
- Produces test controls: `MockDriver.fault_on_next_gripper` and `MockDriver.fault_on_next_home`
- Consumes: Task 1 speed guard in `SafeDriver.move_to`

- [ ] **Step 1: Add failing fault-latching tests**

Replace the existing hardware-fault test with:

```python
def test_hardware_move_fault_latches_and_blocks_next_motion():
    mock, sd = safe()
    mock.fault_on_next_move = "joint 3 overcurrent"
    with pytest.raises(RuntimeError, match="overcurrent"):
        sd.move_to((0.32, 0.0, 0.35))
    assert "move_to failed" in sd.faulted
    with pytest.raises(SafetyViolation, match="faulted"):
        sd.move_to((0.33, 0.0, 0.35))
    assert len([c for c in mock.commands if c[0] == "move_to"]) == 1


def test_hardware_gripper_fault_latches_and_blocks_next_actuation():
    mock, sd = safe()
    mock.fault_on_next_gripper = "gripper bus fault"
    with pytest.raises(RuntimeError, match="bus fault"):
        sd.set_gripper(0.5)
    assert "set_gripper failed" in sd.faulted
    with pytest.raises(SafetyViolation, match="faulted"):
        sd.set_gripper(0.4)
```

- [ ] **Step 2: Run the two tests and verify RED**

Run:

```bash
PYTHONPATH= .venv/bin/python -m pytest b601/tests/test_safety.py -q \
  -k 'hardware_move_fault or hardware_gripper_fault'
```

Expected: move fault assertion sees `None`; gripper mock lacks injected failure behavior.

- [ ] **Step 3: Add injected gripper failure to `MockDriver`**

Initialize:

```python
self.fault_on_next_gripper = None
```

At the start of `set_gripper`:

```python
if self.fault_on_next_gripper is not None:
    fault, self.fault_on_next_gripper = self.fault_on_next_gripper, None
    self.commands.append(("set_gripper", force, "FAULT"))
    raise RuntimeError(f"mock hardware fault: {fault}")
```

- [ ] **Step 4: Implement the common fail-closed helper**

Add to `SafeDriver`:

```python
def _actuate(self, operation, function, *args):
    try:
        return function(*args)
    except Exception as exc:
        self._faulted = (
            f"{operation} failed: {type(exc).__name__}: {exc}")
        raise
```

Replace raw calls:

```python
self._actuate("move_to", self._d.move_to, xyz, speed)
self._actuate("set_gripper", self._d.set_gripper, force)
```

- [ ] **Step 5: Run focused and safety tests and verify GREEN**

Run:

```bash
PYTHONPATH= .venv/bin/python -m pytest b601/tests/test_safety.py -q
```

Expected: all safety tests pass.

- [ ] **Step 6: Commit**

```bash
git add b601/driver/base.py b601/driver/mock.py b601/tests/test_safety.py
git commit -m "fix: latch B601 raw actuation failures"
```

---

### Task 3: Make homing a separately bounded operation

**Files:**
- Modify: `b601/safety/limits.py`
- Modify: `b601/driver/base.py`
- Modify: `b601/driver/mock.py`
- Test: `b601/tests/test_safety.py`

**Interfaces:**
- Produces: `check_timeout(timeout_s, operation) -> float`
- Changes: `Driver.safe_home(max_joint_velocity, timeout_s)`
- Changes: `SafeDriver.safe_home(timeout_s=30.0)`
- Consumes: Task 2 `SafeDriver._actuate`

- [ ] **Step 1: Add failing timeout and homing-contract tests**

Add the import and tests:

```python
from b601.safety.limits import check_timeout


@pytest.mark.parametrize("timeout", [
    -1.0, 0.0, float("nan"), float("inf"), True, "soon",
])
def test_invalid_home_timeout_is_rejected(timeout):
    with pytest.raises(SafetyViolation, match="safe_home timeout"):
        check_timeout(timeout, "safe_home")


@pytest.mark.parametrize("timeout", [
    -1.0, 0.0, float("nan"), float("inf"), True, "soon",
])
def test_invalid_home_timeout_never_reaches_driver(timeout):
    mock, sd = safe()
    with pytest.raises(SafetyViolation, match="safe_home timeout"):
        sd.safe_home(timeout_s=timeout)
    assert mock.last("safe_home") is None
    assert sd.faulted is not None


def test_safe_home_forwards_bounds_and_counts_motion():
    mock, sd = safe(start=(WS.x_max, 0.0, 0.35))
    sd.safe_home(timeout_s=12.0)
    assert mock.last("safe_home") == (
        "safe_home", LIM.max_joint_velocity, 12.0)
    assert sd.motions == 1


def test_safe_home_fault_latches_and_blocks_later_motion():
    mock, sd = safe()
    mock.fault_on_next_home = "homing timeout"
    with pytest.raises(RuntimeError, match="homing timeout"):
        sd.safe_home(timeout_s=12.0)
    assert "safe_home failed" in sd.faulted
    with pytest.raises(SafetyViolation, match="faulted"):
        sd.move_to((0.32, 0.0, 0.35))


def test_safe_home_rejects_invalid_precondition_without_raw_motion():
    mock, sd = safe(start=(float("nan"), 0.0, 0.35))
    with pytest.raises(SafetyViolation, match="NaN"):
        sd.safe_home(timeout_s=12.0)
    assert mock.last("safe_home") is None
    assert sd.faulted is not None


def test_safe_home_rejects_invalid_postcondition():
    mock, sd = safe()
    mock.home_result = (float("nan"), 0.0, 0.35)
    with pytest.raises(SafetyViolation, match="NaN"):
        sd.safe_home(timeout_s=12.0)
    assert sd.faulted is not None
    assert sd.motions == 0
```

- [ ] **Step 2: Run homing tests and verify RED**

Run:

```bash
PYTHONPATH= .venv/bin/python -m pytest b601/tests/test_safety.py -q \
  -k 'home_timeout or safe_home'
```

Expected: collection fails because `check_timeout` does not exist and the raw
homing signature does not accept bounds.

- [ ] **Step 3: Implement timeout validation**

Add to `b601/safety/limits.py`:

```python
def check_timeout(timeout_s, operation):
    if (isinstance(timeout_s, bool)
            or not isinstance(timeout_s, numbers.Real)
            or not math.isfinite(timeout_s)
            or timeout_s <= 0.0):
        raise SafetyViolation(
            f"{operation} timeout out of range",
            f"{timeout_s!r} must be finite and positive")
    return float(timeout_s)
```

- [ ] **Step 4: Change the raw homing interface and mock**

Change the abstract method:

```python
def safe_home(self, max_joint_velocity, timeout_s):
    """Execute the approved bounded homing route and stop on timeout."""
```

In `MockDriver.__init__` add:

```python
self.fault_on_next_home = None
self.home_result = HOME
```

Replace mock homing with:

```python
def safe_home(self, max_joint_velocity, timeout_s):
    if self.fault_on_next_home is not None:
        fault, self.fault_on_next_home = self.fault_on_next_home, None
        self.commands.append(
            ("safe_home", max_joint_velocity, timeout_s, "FAULT"))
        raise RuntimeError(f"mock hardware fault: {fault}")
    self.commands.append(("safe_home", max_joint_velocity, timeout_s))
    self._pose = tuple(self.home_result)
```

- [ ] **Step 5: Implement `SafeDriver.safe_home` preconditions and postconditions**

Import `check_joint_velocity`, `check_pose`, and `check_timeout`. Replace
`SafeDriver.safe_home` with:

```python
def safe_home(self, timeout_s=30.0):
    self._require_ok()
    try:
        timeout_s = check_timeout(timeout_s, "safe_home")
        check_pose(self._d.eef_pose(), self.workspace)
        check_joint_velocity(
            self._d.joint_state().get("velocities"), self.limits)
    except SafetyViolation as exc:
        self._faulted = exc.reason
        raise

    self._actuate(
        "safe_home", self._d.safe_home,
        self.limits.max_joint_velocity, timeout_s)

    try:
        check_pose(self._d.eef_pose(), self.workspace)
        check_joint_velocity(
            self._d.joint_state().get("velocities"), self.limits)
    except SafetyViolation as exc:
        self._faulted = f"safe_home postcondition: {exc.reason}"
        raise
    self.motions += 1
```

- [ ] **Step 6: Run focused and full safety tests and verify GREEN**

Run:

```bash
PYTHONPATH= .venv/bin/python -m pytest b601/tests/test_safety.py -q
```

Expected: all safety tests pass, including the existing assertion that
`disable()` works while faulted.

- [ ] **Step 7: Commit**

```bash
git add b601/safety/limits.py b601/driver/base.py b601/driver/mock.py \
  b601/tests/test_safety.py
git commit -m "fix: define bounded B601 homing contract"
```

---

### Task 4: Make pin probes repository-interpreter-only

**Files:**
- Modify: `b601/setup/setup.sh`
- Modify: `b601/setup/pin_check.sh`
- Modify: `b601/tests/test_setup_pins.py`
- Modify: `README.md`

**Interfaces:**
- Produces: `B601_BOOTSTRAP_PY` as the setup-only interpreter override
- Removes: `B601_PY` from the pin-check interface

- [ ] **Step 1: Replace the ambient-override test with a failing functional test**

Replace `test_pin_check_refuses_an_ambient_interpreter` with:

```python
def test_pin_check_cannot_be_redirected_to_ambient_interpreter(tmp_path):
    r = run(
        f"bash {PIN_CHECK}",
        B601_PY="/nonexistent/ambient-python",
        B601_PINS=str(tmp_path / "absent.env"),
    )
    assert r.returncode == 1
    assert "no pins.env" in r.stderr
    assert "no repository interpreter" not in r.stderr
```

Add:

```python
def test_setup_uses_distinct_bootstrap_interpreter_name():
    text = SETUP.read_text()
    assert "B601_BOOTSTRAP_PY" in text
    assert "B601_PY" not in text
```

- [ ] **Step 2: Run focused setup tests and verify RED**

Run:

```bash
PYTHONPATH= .venv/bin/python -m pytest b601/tests/test_setup_pins.py -q \
  -k 'redirected_to_ambient or distinct_bootstrap'
```

Expected: the pin script honors the nonexistent `B601_PY`, and setup lacks
`B601_BOOTSTRAP_PY`.

- [ ] **Step 3: Remove the pin-check override**

In `pin_check.sh`, set:

```bash
PY="$REPO/.venv/bin/python"
[ -x "$PY" ] || fail "no repository interpreter at $PY — run 'bash b601/setup/setup.sh env' first"
```

Update the header to state that no interpreter override is accepted.

- [ ] **Step 4: Rename the setup-only bootstrap override**

In `setup.sh`, replace:

```bash
PY="${B601_PY:-python3}"
```

with:

```bash
BOOTSTRAP_PY="${B601_BOOTSTRAP_PY:-python3}"
```

Use `"$BOOTSTRAP_PY" -m venv "$VENV"` only when creating `.venv`.

- [ ] **Step 5: Remove override language from README**

Keep the repository environment warning, but remove:

```text
`B601_PY` overrides the interpreter if needed.
```

Document `B601_BOOTSTRAP_PY` only as an optional one-time setup override:

```text
If `python3` is not the intended interpreter for creating `.venv`, set
`B601_BOOTSTRAP_PY` only on the `setup.sh env` invocation.
```

- [ ] **Step 6: Run setup tests and shell syntax checks and verify GREEN**

Run:

```bash
bash -n b601/setup/setup.sh b601/setup/pin_check.sh
PYTHONPATH= .venv/bin/python -m pytest b601/tests/test_setup_pins.py -q
```

Expected: shell syntax succeeds and all setup-pin tests pass.

- [ ] **Step 7: Commit**

```bash
git add b601/setup/setup.sh b601/setup/pin_check.sh \
  b601/tests/test_setup_pins.py README.md
git commit -m "fix: pin B601 probes to repository interpreter"
```

---

### Task 5: Full verification and scope audit

**Files:**
- Verify only; no planned production changes

**Interfaces:**
- Consumes all prior tasks
- Produces final verification evidence

- [ ] **Step 1: Run shell syntax validation**

```bash
bash -n b601/setup/setup.sh b601/setup/pin_check.sh
```

Expected: exit 0 with no output.

- [ ] **Step 2: Run the complete unpowered test suite**

```bash
PYTHONPATH= .venv/bin/python -m pytest b601/tests -q
```

Expected: all tests pass with zero failures.

- [ ] **Step 3: Run direct regression probes**

Run a short Python probe that:

- injects a move hardware fault and confirms the next move raises
  `SafetyViolation`;
- submits negative and NaN speeds and confirms no raw move is recorded;
- calls `safe_home(timeout_s=12.0)` and confirms the raw command records both
  bounds and the audit count increments.

Expected: every assertion succeeds.

- [ ] **Step 4: Audit repository scope**

```bash
git status --short
git -C /home/demo/github_sow_harnessVLA status --short
git diff HEAD~4..HEAD --stat
```

Expected: B601 worktree clean; simulation worktree unchanged; only B601 files
appear in the four implementation commits.

- [ ] **Step 5: Request read-only code review**

Review the implementation range from the design commit through Task 4 against:

- the approved design spec;
- the B601 plan's bounded primitive and safety requirements;
- the five original review findings.

Expected: no Critical or Important findings remain. Address valid findings
through a new TDD cycle before completion.
