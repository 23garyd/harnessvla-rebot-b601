# Risk log — reBot B601-RS

Live risks and their controls. A risk moves to `mitigated`/`closed` only with
evidence, never on intent.

| Date | Risk | Detail | Control | Status |
|---|---|---|---|---|
| 2026-07-31 | **Unpowered-testing discipline erodes** | The safety layer is only trustworthy if it is exercised. The temptation once hardware works is to test against the arm and let mock coverage rot | Every test in `b601/tests/` runs with the arm unpowered and CI has no hardware; `MockDriver` gains features rather than tests reaching for the real arm | monitoring |
| 2026-07-31 | **Demonstration dataset is irreplaceable** | 120–200 teleop episodes cannot be regenerated — an operator session is gone. Unlike the sim track, `artifacts/` here is NOT disposable | Off-machine backup from the FIRST pilot episode (Day 5, not Day 10); dataset hash recorded in `dataset_card.md`; `datasets/` gitignored but hashes committed | **open — backup target not yet chosen** |
| 2026-07-31 | **Silent physical drift** | A nudged camera mount or drifted calibration produces a systematic position bias that looks like policy error. The sim track's Object-S regression was exactly this shape (+0.078 m, from a stale reference) | `pin_check.sh` gates camera serials AND calibration hash on every launch; Day-3 calibration report records measured error at known table points | monitoring |
| 2026-07-31 | **A guard that cannot see the failure it guards** | Sim precedent: `pin_check` reported "clean" while the released assets were missing, because they were gitignored. A passing check that is structurally blind is worse than no check | Each guard states in its header what it does NOT cover; `pin_check` asserts physical state explicitly rather than inferring it from git | monitoring |
