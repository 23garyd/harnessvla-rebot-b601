# B601 Comparison, Recovery and Execution Evidence

Prepared on 2026-11-14. The implementation uses code already committed on 2026-09-01. This directory collects existing trials from 2026-08-28, not new experiments.

| Technical work | Implementation | Original results and documents |
|---|---|---|
| ACT and harness comparison | [harness](../../../b601/planner/harness.py), [physical I/O](../../../b601/planner/live_io.py) | [Comparison sources and summary](comparison-summary.json), [15 scored trial results](hardware/20260828_071714/results.json) |
| Failure detection, retries and recovery | [Execution safeguards](../../../b601/planner/io_support.py), [per-trial gate](../../../b601/planner/trial_gate.py) | [First investigation](hardware/20260828_074607/results.json), [second investigation](hardware/20260828_082005/results.json), [trial 1 telemetry](hardware/20260828_082005/trial_001.jsonl) |
| Hardware failure example | As above | [Trial 1 video](hardware/20260828_082005/trial_001_agentview.mp4), [video provenance and conversion](hardware/20260828_082005/video-provenance.json) |
| Software boundary checks | [Tests](../../../b601/tests/) | [Output: 89 passed, 1 skipped](verification/2026-11-14-tests.txt) |

## Interpreting the Results

Both baseline and harness scored 12/15. All 12 harness successes completed on the first policy attempt, with no recovery-completed successes. The +20 percentage points in the I stratum cannot be interpreted as proof of an effective recovery mechanism. Baseline figures were checked against page 10 of the original [technical study report](../../../reports/harnessvla_b601_report.pdf); raw baseline data were not rescored. Harness figures were checked against the original JSON records here.

There were 6 recovery-branch entries in the scored round, followed by 6 and 4 in the two investigation rounds: 16 total, with no recorded successful held-object grasp from recovery. This explains the different scopes of 0/10 in some investigation-round registry entries and 0/16 in later technical notes covering all three rounds. Branch entry does not guarantee the arm executed descent and gripper closure; the program refuses to continue when convergence is not achieved.

For trial 3 in `20260828_082005`, the original JSON says `success`, while the technical record retains an operator `fail` judgment. The original files and unresolved dispute are preserved, and this trial is not mixed into the 15 scored trials in `071714`. Its telemetry is also retained.

## Provenance and Artifact Scope

[Source receipts](hardware/source-receipts.json) record the copied result and telemetry hashes. The video retains the full 38.867-second sequence, reduced in resolution and re-encoded; trial 1 ended with `gave_up`. It is not a recovery-success, hazard-abort or wireless-link-degradation demonstration. Today's HEAD alone cannot establish the exact historical software runtime state.

This directory does not contain Wi-Fi, Bluetooth or NearLink comparisons, nor coexistence, mobility, energy or scalability experiments. Software recovery and logs can be inspected; wireless comparison results remain missing. Fixed-arm pick-and-place is an existing hardware use case, not automatic evidence that two representative industrial scenarios were demonstrated.

[implementation-commits.csv](implementation-commits.csv) maps actual code-change commits; [manifest.csv](manifest.csv) checks the technical artifacts. Approval reports and invoices are not included here.
