# Runbook — B601 live demonstration

**Status: not yet written.** This is a **Day-20 acceptance gate**: the mentor
must be able to follow this document and start one trial without help.

It is created empty on Day 0 deliberately. A runbook written on Day 20 from
memory describes the system you think you built; one grown from Day 2 onward,
as each step is first performed, describes the one you actually built.

## To fill in as each capability lands
- [ ] Power-on and e-stop check (Day 2)
- [ ] Enable, safe-home, verify joint state (Day 2)
- [ ] Replace the provisional limits with measured ones, then validate the
      envelope: `PYTHONPATH= .venv/bin/python -m b601.safety.config` (Day 2)
- [ ] Repeatability run — 5 poses × 4 cycles, the gate's twenty motions:
      `PYTHONPATH= .venv/bin/python -m b601.bringup.repeatability --out artifacts/day2/repeatability.csv`
      Add `--operator-confirmed` **only after** watching the run and seeing no
      collision and no manual correction; the harness cannot see either, and
      will not pass the gate without you saying so (Day 2)
- [ ] Set `home.tolerance_m` in `limits.yaml` from the measured repeatability,
      then re-validate the envelope (Day 2)
- [ ] Camera start, serial verification, calibration check (Day 3)
- [ ] `pin_check.sh` — expected output and what a failure means (Day 3)
- [ ] Workspace reset and object placement (Day 6)
- [ ] Start a single harness trial (Day 15)
- [ ] Read the result: where artifacts land, how to tell success from abort (Day 15)
- [ ] Recovery: what to do on a safety fault or hardware fault (Day 19)
- [ ] Cold-start rehearsal procedure (Day 19)
