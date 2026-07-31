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
Day 0 scaffold. 94 tests green (`bash b601/setup/setup.sh verify`), no
hardware powered, no data collected.

## Read first
1. `docs/sim_findings_that_transfer.md` — measured results from the sim track
   with their consequences for design here
2. `b601/registry/risk_log.md` — one risk is **open**: dataset backup target
3. `b601/safety/limits.py` — the chokepoint everything routes through

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
