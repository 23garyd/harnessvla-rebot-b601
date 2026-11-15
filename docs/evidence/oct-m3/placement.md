# Technical notes on inference and compute task deployment

Record date: 2026-11-14; compiled from existing technical materials through 2026-08-25 and the current execution entry points. No new deployment experiments were conducted here.

| Deployment mode | Facts supported by existing materials | Verification boundary |
|---|---|---|
| robot-local | Policy execution, arm control, and camera capture on EPYC; [2026-08-22 physical robot telemetry](hardware/20260822_213019/trial_001.jsonl) and video allow inspection of actual execution | Single-machine execution records do not establish latency under other network conditions |
| edge | ASUS/A6000 used for simulation and batch processing; historical technical materials describe the division of training and compute work | Remote training and batch processing do not establish an evaluation of online edge inference; this directory contains no such run results |
| hybrid | Division of work between local execution and remote training | This does not establish verification of combined local and remote online inference; configurations and comparison records for all three modes on the same task are not yet available |

Review entry points: [execution program](../../../b601/planner/run_harness.py), [actual I/O](../../../b601/planner/live_io.py), and [experiment record snapshot](snapshot-2026-08-25/b601_progress_log.md).

Completing the inference deployment evaluation requires recording the components actually running in each mode, model and software versions, tasks, machine configurations, raw logs, and results. Current materials establish only the existing execution and division of work; they cannot replace those evaluation results.
