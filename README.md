# harnessvla-rebot-b601

Memory-guided manipulation with the **reBot B601-RS**: a planner-staged frozen
ACT grasp primitive wrapped in observe → stage → grasp → verify → transport →
retry, with task-specific and global memory.

Companion to [`harnessvla-sim-reproduction`](https://github.com/23garyd/harnessvla-sim-reproduction),
which reproduced the HarnessVLA result in simulation on LIBERO-Pro. What
transferred from that work — and what it cost to learn — is in
[`docs/sim_findings_that_transfer.md`](docs/sim_findings_that_transfer.md).
Read it before designing the verification or memory layers.

## Status

**Day 0 — scaffold.** No hardware powered, no data collected, no experiment
version frozen. Every limit in `b601/setup/limits.yaml` is provisional pending
Day-2 measurement.

## Layout

| path | what |
|---|---|
| `b601/safety/` | workspace + motion limits (`config.py` loads and validates `limits.yaml`). **Every motion routes through here** |
| `b601/driver/` | driver interface, `SafeDriver` chokepoint, mock, B601 adapter |
| `b601/cameras/` | capture config, calibration, sync checking |
| `b601/primitives/` | analytic observe / stage / transport / release / verify |
| `b601/policy/` | ACT training and the frozen inference server |
| `b601/planner/` | the harness loop: stage → grasp → verify → retry → memory |
| `b601/analysis/` | vendored from the sim repo — see `analysis/VENDORED.md` |
| `b601/registry/` | experiment registry, risks, progress, deviations, dataset card, calibration |
| `b601/setup/` | `pin_check.sh` (software **and** physical pins), limits, env |
| `b601/bringup/` | Day-2 repeatability harness, gate check, FK cross-check |
| `b601/tests/` | all runnable with the arm unpowered |
| `datasets/` `checkpoints/` `artifacts/` | gitignored; hashes committed |

## Two conventions that are not negotiable

**1. Nothing bypasses the safety chokepoint.** Primitives, planner and policy
all hold a `SafeDriver`, never a raw driver. A policy that emits an
out-of-bounds action gets that action rejected and latches a fault; it does
not get a clamped version of a wild command. Anything that fails mid-motion —
driver exception, operator interrupt — latches too: after uncertain actuation
the arm is not where the last command said it was, and every later step check
would be measured from a stale pose.

What the chokepoint does **not** cover: `safe_home()` is fault-latched and
counted but not path-checked, because homing is a joint-space trajectory this
layer never sees. Its bounded contract is a Day-2 deliverable and it must not
run under power before then. Guards state their gaps here rather than leaving
them to be discovered.

**2. The test suite never needs hardware.** If a test would need the arm,
extend `MockDriver` instead. Safety code you can only exercise by powering the
robot is safety code you will stop exercising.

## Commands

```bash
bash b601/setup/setup.sh env          # once per machine: .venv + pinned deps

# every session
bash b601/setup/pin_check.sh          # gates software AND physical pins
bash b601/setup/setup.sh verify       # the unpowered suite, in the repo venv
```

Both commands run under the repository interpreter. Do not invoke them with an
ambient `python`: on a machine with another environment on `PATH` that checks
a different install than the one `setup.sh env` created, which is how a pin
gate ends up verifying nothing. If `python3` is not the intended interpreter
for creating `.venv`, set `B601_BOOTSTRAP_PY` only on the `setup.sh env`
invocation.

```bash
# after editing the safety envelope (Day 2), before any powered motion
PYTHONPATH= .venv/bin/python -m b601.safety.config
```
