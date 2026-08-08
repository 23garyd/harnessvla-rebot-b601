# Handover — harnessvla-rebot-b601

## What this is
Real-hardware companion to the HarnessVLA simulation reproduction. Goal
(plan §1): show that a planner can make a **frozen, imperfect** learned grasp
primitive more reliable by staging it, inspecting the outcome, re-grounding,
and retrying.

Explicitly NOT in scope: running the released LIBERO pi0.5 checkpoint on the
B601. The learned primitive here is a B601-specific ACT policy trained from
teleoperated demonstrations.

## Where things stand (2026-08-07 evening)
Day 3-4 bring-up. 495 tests green in the unpowered suite (`PYTHONNOUSERSITE=1
PYTHONPATH= .venv/bin/python -m pytest b601/tests/ -q`). Teleop verified,
cameras verified, pins verified, **zero episodes recorded** — one physical
blocker stands between here and the first episode (next section).

**The 0-frame D405 saga is CLOSED.** It was two stacked defects, neither of
them the USB link (the D405 now sits on a verified USB 3.2 / 5 Gbps cable):
1. **Vendor null-frame bug, fixed** — vendor commit `3b4f877`,
   `LEROBOT_ORIGIN` re-pinned. A colour-only frameset's `get_depth_frame()`
   returns a null frame (falsy, never None); the wrapper's `is not None`
   check then exploded on every frameset and the read loop suppressed it
   forever. Verified after fix: `async_read` 90/90 at 30.4 fps.
2. **One-session-per-reset firmware behaviour, worked around** — the D405
   (fw 5.12.14.100) streams exactly ONE pipeline session per hardware reset;
   every later session opens fine and delivers nothing. Preflight's own
   liveness grab was killing the recording after it. `b601.cameras.reset`
   plus re-`capture` now run before preflight AND before `lerobot-record`
   inside `record_session.sh`. If a manual camera check leaves the D405
   dead, that is normal — reset, don't debug. Candidate real fix is a
   firmware update: owner decision, in the risk log, not scheduled.

Full story: risk_log.md rows of 2026-08-06/07, protocol_deviations.md (two
vendor patches), RUNBOOK.md "one pipeline session per reset" item.

## EVERY MORNING — the power-up ritual (all of it recurs per boot)
1. **Power the arm, bring up CAN** (needs sudo, password location is in the
   session memory): `sudo ip link set can0 up type can bitrate 1000000`
2. **Mount the backup drive** (no sudo needed; udisks mounts do NOT survive
   a reboot, and the record script's backup gate fails without it —
   measured 2026-08-08, first thing it caught):
   `udisksctl mount -b /dev/disk/by-uuid/b0b0d284-79d6-4291-93ad-f27ef2f77022`
   By UUID, never by /dev/nvmeXn1pY — four identical OWC drives are
   installed and the kernel demonstrably shuffles their numbering across
   reboots.
3. **Park the arm in its session-start pose** — the drift reference was
   recorded with it there, clear of every marker sightline. (2026-08-08: the
   morning drift failure was real — camera nudged during cable work AND the
   arm's old park pose occluded marker id1. Reference re-recorded, 4 ArUco
   landmarks, all 30/30 stable; the faint id11 tag was replaced.)
4. **Record:**
   `bash b601/setup/record_session.sh "<task>" <episodes>`
   The script gates everything (pins, D405 resets, capture, preflight,
   backup) and prints the replay command at the end.
5. **Replay and watch the arm** — the Day-5 gate is a human judgement.

Still open behind that: eye_in_hand exposure is a PLACEHOLDER (8000 µs,
chosen not measured — confirm fingers are resolvable under workspace
lighting); staging method decision (metric vs image-space) — decide together
with the block-placement region before scaled collection, since the scatter
region must be one the staging method can address; backup is on-machine
only; the two markers on the black board (id1/id6) — confirm whether the
board is fixed relative to the arm or can slide, asked twice, never
answered.

**Before powered motion beyond teleop:** `safe_home()` guards its endpoints
but the trajectory between them is still the vendor driver's — as are timeout
enforcement, acceleration and collision. Risk log, open. Confirm the vendor
homing routine honours the velocity bound (`vlim: 10.0` vendor vs our 1.0
rad/s) before any powered homing. **Do not run `example/2_zero_and_read.py`**
— it rewrites motor zero offsets in NVM.

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
- **D405 firmware update** — 5.12.14.100 is early firmware and the
  one-session-per-reset behaviour smells like a known-fixed defect; updating
  would remove the reset workaround but carries a small brick risk and
  changes pinned hardware state (owner call)
- **Backup is on-machine only** — `/media/demo/b0b0d284.../b601` is a second
  internal NVMe: protects against disk failure, not machine loss. The risk
  as written says OFF-machine
- **Staging method** (metric transform vs image-space) — decide before
  scaled collection
- All values in `b601/setup/limits.yaml` are provisional, pending Day-2
  measurement
- The fixed camera already uses the `agentview` name — it is frozen into the
  dataset feature names at record time

## Plan gates worth knowing
| Day | Gate |
|---|---|
| 2 | 20 consecutive low-speed motions, no fault or manual correction |
| 5 | ≥9 of 10 episodes replay correctly; stack approved for scaled collection |
| 10 | Automated dataset audit passes; zero held-out leakage |
| 14 | ≥70% held-out grasp success, zero safety violations |
| 18 | Retry-enabled success ≥85% **or** +15pp over one-shot, zero safety events |
| 20 | Mentor can follow `RUNBOOK.md` to start one trial |
