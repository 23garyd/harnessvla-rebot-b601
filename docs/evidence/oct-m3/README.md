# B601 Hardware Implementation and Technical Evidence Index

Prepared on 2026-11-14. Implementation baseline: `689526cdf4ec9126fec67f1a3017cb443893752f`.
This update adds a technical index, existing trial artifacts and verification records. It does not change control programs, retrain models or add hardware trials. Source code already exists at the baseline commit.

| Feature | Implementation | Inspectable technical evidence |
|---|---|---|
| Observation, localization, grasping, verification, retries and placement | [State machine](../../../b601/planner/harness.py), [execution entry point](../../../b601/planner/run_harness.py), [physical I/O](../../../b601/planner/live_io.py) | [Hardware trial artifacts](hardware/20260822_213019/), [historical technical record](snapshot-2026-08-25/b601_progress_log.md) |
| Visual grasp verification and planning support | [Verifier](../../../b601/planner/grasp_verifier.py), [perception](../../../b601/planner/perception.py) | [Test output](verification/2026-11-14-tests.txt) |
| Bounded execution and exceptional termination | [Actual execution safeguards](../../../b601/planner/io_support.py), [hardware execution path](../../../b601/planner/live_io.py), [generic safety driver](../../../b601/driver/base.py) | [Execution tests](../../../b601/tests/test_live_servo.py), [safety tests](../../../b601/tests/test_safety.py), [test output](verification/2026-11-14-tests.txt) |
| State feedback and per-step logging | [TickRecorder](../../../b601/planner/live_io.py) | [Trial 1 telemetry](hardware/20260822_213019/trial_001.jsonl) |
| Dataset and policy provenance | [Dataset record snapshot](snapshot-2026-08-25/b601_dataset_card_168_episodes.md), [current experiment registry](../../../b601/registry/experiment_registry.md) | Raw data and weights are not included here; see the limitations below |
| Deployment allocation | [Deployment notes](placement.md) | Existing allocation and configuration, without a measured comparison of all three inference placements |

## Interpreting the Artifacts

The [2026-08-22 hardware record](hardware/20260822_213019/results.json) contains all five trial results; only trial 1 has full-sequence video and step-level telemetry attached here. Its recorded outcome is `gave_up` after three attempts, not evidence of task success.

The [video](hardware/20260822_213019/trial_001_agentview.mp4) was re-encoded from the original 155,260,459-byte file to 640 pixels wide, without cutting the sequence or adding actions. The original file hash matches the repository's [original manifest](../../../b601/registry/harness_trials_manifest.csv). Conversion commands, original hashes and artifact hashes are in the [provenance record](hardware/20260822_213019/provenance.json). Video playback duration and the trial's recorded wall-clock duration are different metrics and are not interchangeable.

`snapshot-2026-08-25/` is a byte-level snapshot of existing technical documents describing the then-current 168-episode dataset and experiment status. It is not a rerun of the current version. Current code and historical evidence have separate versions and dates.

## Verification

The [2026-11-14 output](verification/2026-11-14-tests.txt) records 187 passing no-hardware tests. It does not establish that the full test suite, hardware trials or a degraded-mode demonstration passed. Run the listed commands in the repository's required dependency environment.

This repository contains both a `SafeDriver` abstraction and a lerobot-based hardware path. Generic driver tests alone do not establish that the actual policy path has the same protection. The index therefore also links to `live_io.py`, `io_support.py` and their tests.

## Not Established by These Artifacts

- No new physical degraded-mode or action-refusal demonstration is provided. Software tests and ordinary trial footage do not replace one.
- A grouped evaluation of robot-local, edge and hybrid inference placements is not available.
- The 168-episode raw dataset and policy weights remain in the original experiment storage. Data cards are not downloadable datasets or models, and this index does not claim those large files are committed or externally retrievable.

[manifest.csv](manifest.csv) records each technical artifact's byte count, SHA-256 and provenance.

[implementation-commits.csv](implementation-commits.csv) maps each feature to its implementation files, the historical commits that last changed them, code links at the full baseline, and artifact paths. Historical implementation commits remain separate from evidence-packaging commits so documentation work is not presented as new implementation.
