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
