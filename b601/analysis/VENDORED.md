# Vendored modules — provenance

These files are **copies**, not a dependency:

    schemas.py  build_ledger.py  compare.py  disk_guard.py  manifests.py

Source: `github.com/23garyd/harnessvla-sim-reproduction` at commit `ffb0022`
(verified byte-identical at that commit and at the sim repo's later HEAD).
Copied 2026-07-31.

**Why copied rather than depended on:** a shared package or submodule would
add version coupling between two projects with different lifetimes, different
pin regimes and a 20-day horizon. Divergence is the expected and acceptable
outcome — B601 records physical state that the sim schema has no concept of.

**Consequence:** upstream fixes do NOT flow here automatically. If a bug is
found in one copy, fix both and note it here.

## Divergence from the sim copy (2026-07-31)

`schemas.py` and `build_ledger.py` have diverged. This was expected, but it
was not yet done, and until it was the copies were carrying sim assumptions
onto hardware:

- **`run_meta` now requires `pins`** (`lerobot_version`, `camera_serials`,
  `calibration_sha256`) and rejects placeholder values. `pin_check.sh` gated
  the physical regime at launch while the record it gated stored none of it,
  so no episode could be attributed to a camera configuration afterwards.
- **`suite` and `rpent_commit` are gone**, replaced by `repo_commit`. Both
  were LIBERO/RPent concepts; nothing on this track runs RPent.
- **`safety_abort` is a validity status**, requiring evidence, excluded from
  scoring and reported separately by `compare.py`. It had no terminal
  category, so a latched SafeDriver fault could only be filed as an ordinary
  task failure.
- **`build_ledger.py` imported `track.analysis.schemas`** — the sim repo's
  package path. The module could not be imported here at all.
- **`compare.summarize` raised on zero scored pairs** (`wilson_interval(0,0)`).
  Reachable here whenever exclusions empty a cell; now reports `0/0`.

The import path was a vendoring miss, not an upstream bug — `track.analysis`
is correct in the sim repo. The zero-pair crash IS latent upstream and should
be fixed there. Everything else is deliberate divergence and must NOT be
back-ported.

**What each is for:**
- `schemas.py` — validates `run_meta.json` / `result_row.json`. Will need B601
  fields (camera manifest hash, calibration hash, policy checkpoint sha).
- `build_ledger.py` — walks run dirs into a ledger CSV; skips runs without a
  result row.
- `compare.py` — paired comparison with Wilson 95% intervals. This is the
  Day-18 one-shot-vs-harness statistic, already written.
- `disk_guard.py` — artifact budget check before a run starts.
- `manifests.py` — frozen queue manifests; validation + cell expansion.
