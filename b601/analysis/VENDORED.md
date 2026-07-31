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

**What each is for:**
- `schemas.py` — validates `run_meta.json` / `result_row.json`. Will need B601
  fields (camera manifest hash, calibration hash, policy checkpoint sha).
- `build_ledger.py` — walks run dirs into a ledger CSV; skips runs without a
  result row.
- `compare.py` — paired comparison with Wilson 95% intervals. This is the
  Day-18 one-shot-vs-harness statistic, already written.
- `disk_guard.py` — artifact budget check before a run starts.
- `manifests.py` — frozen queue manifests; validation + cell expansion.
