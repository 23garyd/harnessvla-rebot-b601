# Handover — harnessvla-rebot-b601

## What this is
Real-hardware companion to the HarnessVLA simulation reproduction. Goal
(plan §1): show that a planner can make a **frozen, imperfect** learned grasp
primitive more reliable by staging it, inspecting the outcome, re-grounding,
and retrying.

Explicitly NOT in scope: running the released LIBERO pi0.5 checkpoint on the
B601. The learned primitive here is a B601-specific ACT policy trained from
teleoperated demonstrations.

## Where things stand (2026-08-24)

Days 6–18 complete. **566 tests green** in the unpowered suite
(`PYTHONNOUSERSITE=1 PYTHONPATH= .venv/bin/python -m pytest b601/tests/ -q`).
Zero open risks (7 monitoring, 2 mitigated).

| | |
|---|---|
| Dataset | **168 certified episodes**, 96,058 frames, zero held-out leakage (`b601_train_final168_20260812`) |
| Policy | ACT 52M trained to loss **0.062**; `artifacts/act_b601_v1_20260812`, 2.9 G |
| **Day-14 gate** | **FAILED — held-out 0/10, in-distribution 3/5.** Primitive frozen anyway, *as an imperfect primitive*: this is the profile the harness thesis presupposes, and a harder test than the plan's ≥70% assumption |
| Harness | Loop state machine, live I/O, grasp verifier (**416/417 holds**), staging table (LOO p90 < 6°) |
| Live shakedowns | **4 run**, 30 live trials + 10 dry, 40 videos in `outputs/harness_trials` (3.8 G) |
| Day-18 bar | +15 pp over the one-shot primitive |

**The diagnosis chain is the result so far**, not the pass rate:

1. Operator-in-frame makes the policy retreat — proven by occlusion probe, a
   107×120 px patch flips the behaviour. Training tails taught it that a
   person in view means the episode is over.
2. With the operator out of frame, 5 of 7 policy segments continue from the
   staged pose (0 of 7 before), and the verify → place-recovery branch fired
   live for the first time.
3. Closed fingers plowed the cube: open-loop approach plus a lagging gripper.
   Fixed by opening the gripper first, closed-loop, at quarter speed.
4. With that fixed, the wall is staging accuracy: **no open-loop table can
   stage where no demonstration went** — but the wrist camera saw the block in
   9 of 9 attempts.

**Current frontier:** a wrist-image servo phase after staging (landed
2026-08-23, `72732d1`) drives the block's wrist-frame centroid to the
demonstrated pre-grasp target using measured pan (−12.8 px/deg).
**Not yet tried on hardware** — that is the next session.

### SAFETY EVENT, 2026-08-14 — read this before touching the eval path
A stall broke the arm because **the safety layer was absent from the eval
path**. The chokepoint the whole design is built around was not in the loop
that ran the policy. Per-tick and per-joint clamps, command-stream rate limits
and the safety-event mechanism were all corrected the same day. Treat any new
execution path as unguarded until you have shown otherwise — this is the
physical form of the sim track's "a guard that cannot see the failure it
guards".

## EVERY MORNING — the power-up ritual (all of it recurs per boot)
1. **Power the arm, bring up CAN** (needs sudo, password location is in the
   session memory): `sudo ip link set can0 up type can bitrate 1000000`
2. **Backup drive mounts itself since 2026-08-10** — an fstab entry
   (UUID=b0b0d284…, `nofail`) mounts it at **`/mnt/nvme3`** on every boot,
   retiring the manual udisksctl step and the mount-missing morning failure
   it existed for. Scripts point at `/mnt/nvme3/b601`. If the backup gate
   ever fails again, check `findmnt /mnt/nvme3` first — and mount by UUID,
   never /dev/nvmeXn1pY: four identical OWC drives shuffle numbering across
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
only. RESOLVED 2026-08-08: the black board is fixed relative to the arm
(operator confirmed), so its two markers (id1/id6) are valid drift
landmarks. Watch cable routing instead — the D405's short wrist cable
drooped over id1 mid-session and failed the gate; a USB 3 extension (not
USB 2, which forecloses wrist depth while the staging method is undecided)
is the durable fix.

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
- **Backup is on-machine only** — `/mnt/nvme3/b601` is a second
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
