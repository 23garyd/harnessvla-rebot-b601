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

### Day 0 addendum — inheritance review of the vendored analysis layer

External review asked whether the sim→B601 inheritance path is sound. The
architecture is (findings + analysis tooling + RPent read at a pin; no
released checkpoint), but the vendored copies still carried sim assumptions:

| Defect | Consequence had it survived |
|---|---|
| `run_meta` stored no physical pins | `pin_check.sh` gated camera serials and calibration at launch; the record stored neither, so Day-18 could not attribute an episode to a configuration |
| No `safety_abort` terminal status | A latched SafeDriver fault could only be filed as `valid_failure` — counted as a task failure, absorbed into the rate the Day-18 "zero safety events" gate reads |
| `build_ledger` imported `track.analysis` | The vendored module could not be imported in this repo at all |
| `compare.summarize` raised on 0 pairs | Any Day-18 rebuild where exclusions emptied a cell would crash instead of reporting 0/0 |
| `limits.yaml` had no loader | Day-2 measured limits would have changed nothing; the file was documentation, not data |

Fixed with 47 new tests (47 → 94). Divergence from the sim copies is recorded
in `b601/analysis/VENDORED.md`; the zero-pair crash is latent upstream too.
No limit VALUES changed — the envelope is still the provisional Day-0 one.
