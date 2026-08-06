# Handover — harnessvla-rebot-b601

## What this is
Real-hardware companion to the HarnessVLA simulation reproduction. Goal
(plan §1): show that a planner can make a **frozen, imperfect** learned grasp
primitive more reliable by staging it, inspecting the outcome, re-grounding,
and retrying.

Explicitly NOT in scope: running the released LIBERO pi0.5 checkpoint on the
B601. The learned primitive here is a B601-specific ACT policy trained from
teleoperated demonstrations.

## Where things stand
Day 0-2 software. 291 tests green (`bash b601/setup/setup.sh verify`), no
hardware powered, no data collected.

**Before powered motion:** `safe_home()` now guards its endpoints (timeout,
preconditions, arrival at the approved `HomeContract`, fault latching) but the
trajectory between them is still the vendor driver's — as are timeout
enforcement, acceleration and collision. Risk log, open. Confirm the vendor
homing routine honours the velocity bound before any powered homing.

**Day-2 gate is NOT met** — no hardware has been powered. See the Day-2 entry
in `b601/registry/progress_log.md` for the full remaining list; the largest
items are `b601/driver/b601.py` against the vendor SDK, measured limits, and
the twenty-motion repeatability run.

## Machines
| Machine | Role |
|---|---|
| **EPYC + RTX 5090** | Robot PC — CAN, cameras, teleop, recording, training, inference, demo |
| **ASUS + A6000** | Fallback robot PC until the `sm_120` gate passes; spare capacity after |
| **Ubuntu + 2× Titan Xp** | Development and CI only — Pascal is on a driver/toolchain support cliff |

Rationale, including why the Titan Xp box is *not* the robot PC, is in
`b601/registry/protocol_deviations.md`. The 5090 matches the plan's stated
platform, so this is an allocation record rather than a deviation.

`bash b601/setup/setup.sh env` builds a **test** environment, not a
robot-ready one: `requirements.txt` leaves the vendor stack as unpinned
placeholders until it is validated on the robot PC. See the "Before the arm"
section of `RUNBOOK.md` for the install and the `sm_120` gate that precedes
CAN bring-up.

## Read first
1. `docs/sim_findings_that_transfer.md` — measured results from the sim track
   with their consequences for design here
2. `b601/registry/risk_log.md` — open risks, and the control for each
3. `b601/registry/progress_log.md` — day-by-day, with the defect tables. The
   commit messages carry the same reasoning if you prefer `git log`
4. `docs/reference_material.md` — the vendor API as it actually behaves:
   three plugin hazards, the URDF/frame/joint facts, the FK and IK
   measurements. Read before touching `b601/driver/b601.py`
5. `b601/safety/limits.py` and `b601/driver/base.py` — the chokepoint
   everything routes through, and the section stating what it does **not**
   cover

Starting a fresh session on the robot PC? Reading those five in order
reconstructs the current picture; nothing important lives outside the
repository.

## Open decisions
- **Dataset backup target** (needed before the first pilot episode, Day 5)
- All values in `b601/setup/limits.yaml` are provisional, pending Day-2 measurement
- Whether the fixed camera occupies the sim harness's `agentview` slot naming,
  which would let the released prompt idiom be reused rather than rewritten

## Plan gates worth knowing
| Day | Gate |
|---|---|
| 2 | 20 consecutive low-speed motions, no fault or manual correction |
| 5 | ≥9 of 10 episodes replay correctly; stack approved for scaled collection |
| 10 | Automated dataset audit passes; zero held-out leakage |
| 14 | ≥70% held-out grasp success, zero safety violations |
| 18 | Retry-enabled success ≥85% **or** +15pp over one-shot, zero safety events |
| 20 | Mentor can follow `RUNBOOK.md` to start one trial |
