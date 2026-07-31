# Progress log — reBot B601-RS

One entry per working day. **Every entry that produces numbers embeds the
result table** — not a summary of it. This convention is carried over from the
simulation track, where it repeatedly turned out to be the only place a claim
could be checked against its evidence.

## Day 0 — repo scaffold (2026-07-31)

Before Day 1, so Day 1 is charter and safety rather than directory layout.

- Structure: `b601/{safety,driver,cameras,primitives,policy,planner,analysis,registry,manifests,setup,tests}`.
- **Safety layer first** (`b601/safety/limits.py` + `SafeDriver`): one chokepoint
  every motion passes through, pure functions, limits as data in
  `setup/limits.yaml` (all values PROVISIONAL pending Day-2 measurement).
- **Mock driver first** (`b601/driver/mock.py`): the whole suite runs with the
  arm unpowered, including induced empty grasps for the Day-16 verifier.
- **28 safety tests green**, no hardware.
- `pin_check.sh` gates two regimes: software (LeRobot) and **physical**
  (camera serials + calibration hash).
- Analysis modules vendored from `harnessvla-sim-reproduction@ffb0022`
  (`schemas`, `build_ledger`, `compare`, `disk_guard`, `manifests`) — verified
  identical at that commit and at the sim repo's later HEAD.
- Open: dataset backup target undecided; all limits provisional; no hardware
  powered; no data collected.
