# Experiment registry — reBot B601-RS

Every behaviour-affecting configuration gets a version tag here **before** any
run uses it. Runs record their tag in `run_meta.json`. A version bump
invalidates affected evaluation cells.

Unlike the simulation track, the version axis here is **physical as well as
software**. A changed camera serial, mount, exposure or calibration is a new
version and invalidates the episodes recorded under the old one — the plan is
explicit that camera state is experiment state.

| Version | Date | Software pins | Physical pins | Policy | Notes |
|---|---|---|---|---|---|
| v0 | 2026-07-31 | none — scaffolding only, no runs | none | none | Repo scaffolded: safety layer, mock driver, pin_check (software + physical), vendored analysis modules. No hardware powered, no data collected. First real version is v1, frozen at the Day-1 mentor gate with the safety boundary. |
| v1-pending | 2026-08-06 | `pins.env` recorded: interpreter `miniforge3/envs/lerobot`, lerobot 0.4.4 `editable+git:fe078af`, placo 0.9.23, seeed-b601 1.0.1 | URDF `2012b5aa3b58`@`gripper_end`; cameras `353322271941,DSJ-250318-J`; calibration `0c26d532b47c` | none | **NOT a frozen version.** The pins exist and verify, so an episode recorded now COULD be attributed — but the Day-1 mentor acceptance gate is still unevidenced in this repository, and the plan freezes v1 at that gate. Recorded here so the configuration that produced any pilot data is identifiable, not to claim the gate. `eye_in_hand.exposure` is still a placeholder and the drift reference covers the fixed camera only. |
| v1-pending (updated) | 2026-08-08 | lerobot re-pinned twice for vendor camera fixes: `fe078af` -> `e77868a` (OpenCV config `copy` attribute) -> `3b4f877` (colour-only RealSense null-frame bug); both in `protocol_deviations.md` | calibration re-recorded `a80f3c57b141` (four ArUco landmarks, 2026-08-07) -> `cbe222c033a9` (three landmarks, 2026-08-08) after the drift gate caught the top camera nudged during cable work and marker id1 relocated out of the arm's park footprint; details in `calibration_report.md` | none | Still no frozen version and still zero episodes, so no data is invalidated by either change. Top-right landmark (id11) excluded as marginal — replace its tag and re-record before scaled collection. `eye_in_hand.exposure` still a placeholder. |
