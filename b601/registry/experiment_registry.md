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
