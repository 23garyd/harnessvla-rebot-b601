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
| `b601/safety/` | workspace + motion limits. **Every motion routes through here** |
| `b601/driver/` | driver interface, `SafeDriver` chokepoint, mock (no hardware) |
| `b601/cameras/` | capture config, calibration, sync checking |
| `b601/primitives/` | analytic observe / stage / transport / release / verify |
| `b601/policy/` | ACT training and the frozen inference server |
| `b601/planner/` | the harness loop: stage → grasp → verify → retry → memory |
| `b601/analysis/` | vendored from the sim repo — see `analysis/VENDORED.md` |
| `b601/registry/` | experiment registry, risks, progress, deviations, dataset card, calibration |
| `b601/setup/` | `pin_check.sh` (software **and** physical pins), limits, env |
| `b601/tests/` | all runnable with the arm unpowered |
| `datasets/` `checkpoints/` `artifacts/` | gitignored; hashes committed |

## Two conventions that are not negotiable

**1. Nothing bypasses the safety chokepoint.** Primitives, planner and policy
all hold a `SafeDriver`, never a raw driver. A policy that emits an
out-of-bounds action gets that action rejected and latches a fault; it does
not get a clamped version of a wild command.

**2. The test suite never needs hardware.** If a test would need the arm,
extend `MockDriver` instead. Safety code you can only exercise by powering the
robot is safety code you will stop exercising.

## Commands

```bash
# every session
bash b601/setup/pin_check.sh          # gates software AND physical pins
PYTHONPATH= python -m pytest b601/tests/ -q
```
