# Runbook — B601 live demonstration

**Status: not yet written.** This is a **Day-20 acceptance gate**: the mentor
must be able to follow this document and start one trial without help.

It is created empty on Day 0 deliberately. A runbook written on Day 20 from
memory describes the system you think you built; one grown from Day 2 onward,
as each step is first performed, describes the one you actually built.

## Before the arm — environment on the robot PC (Day 2)

These come first because a failure here is cheap, and the same failure
discovered after CAN bring-up and calibration is not.

- [ ] Clone and build the environment. `setup.sh env` gives a **test**
      environment, not a robot-ready one — `requirements.txt` deliberately
      leaves the vendor stack as unpinned placeholders until it is validated
      on this machine:
      ```
      git clone https://github.com/23garyd/harnessvla-rebot-b601.git
      cd harnessvla-rebot-b601
      bash b601/setup/setup.sh env
      bash b601/setup/setup.sh verify      # expect: 291 passed, 2 skipped
      ```
      Set the git identity too — it lives in `~/.gitconfig`, not in the repo.
- [ ] Install the vendor stack. Install the **Seeed fork**, not upstream
      HuggingFace, and prefer a VCS pin over `pip install -e`: an editable
      clone is identified only by its git HEAD, and a dirty tree cannot be
      pinned at all.
      ```
      .venv/bin/pip install "lerobot[kinematics] @ git+https://github.com/Seeed-Projects/lerobot@<commit>"
      .venv/bin/pip install lerobot-robot-seeed-b601 motorbridge
      ```
- [ ] **GATE — Blackwell check. Run this before CAN setup, not after.** The
      5090 needs working `sm_120` kernels for *both* training and inference;
      if LeRobot's dependency resolution pins a torch without them, this
      machine cannot run the policy at all.
      ```
      .venv/bin/python -c "import torch; print(torch.__version__, torch.cuda.get_arch_list())"
      .venv/bin/python -c "import torch; print(torch.zeros(1).cuda() + 1)"
      ```
      `sm_120` must appear in the arch list and the second line must not
      throw. **If it fails, stop and move to the A6000 machine** (`sm_86`) —
      see the platform decisions in `b601/registry/protocol_deviations.md`.
      Do not release the A6000 until this passes.
- [ ] Fetch the kinematic model. The URDF is not in this repository; it ships
      with the vendor sources. Keep `meshes/` alongside the URDF — placo
      resolves mesh paths against the URDF **file**, and the vendor ships it
      one level below the meshes.
      ```
      git clone https://github.com/vectorBH6/reBotArm_control_py
      # urdf/00-arm-rs_asm-v3/  -> copy or symlink to b601/setup/urdf/, or set B601_URDF
      ```
- [ ] Cross-check FK before trusting any pose:
      `PYTHONPATH= .venv/bin/python -m b601.bringup.kinematics_check <urdf>`
      Expect max disagreement 0.000000000 m.
- [ ] Pin the versions you just installed into `requirements.txt`, replacing
      the placeholders, then freeze: `bash b601/setup/pin_check.sh --record`
      (needs a non-dirty lerobot checkout and the URDF in place).

## To fill in as each capability lands
- [ ] Power-on and e-stop check (Day 2)
- [ ] Enable, safe-home, verify joint state (Day 2)
- [ ] Replace the provisional limits with measured ones, then validate the
      envelope: `PYTHONPATH= .venv/bin/python -m b601.safety.config` (Day 2)
- [ ] Repeatability run — 5 poses × 4 cycles, the gate's twenty motions:
      `PYTHONPATH= .venv/bin/python -m b601.bringup.repeatability --out artifacts/day2/repeatability.csv`
      Add `--operator-confirmed` **only after** watching the run and seeing no
      collision and no manual correction; the harness cannot see either, and
      will not pass the gate without you saying so (Day 2)
- [ ] Set `home.tolerance_m` in `limits.yaml` from the measured repeatability,
      then re-validate the envelope (Day 2)
- [ ] Confirm the plugin's motor order matches URDF `joint1..joint6` — move one
      joint at a time and check the reported axis. A wrong order gives poses
      that look plausible and are wrong everywhere but home (Day 2)
- [ ] Cross-check FK against the shipped URDF before trusting any pose:
      `PYTHONPATH= .venv/bin/python -m b601.bringup.kinematics_check <urdf>` (Day 2)
- [ ] Set the plugin's `joint_limits` WIDER than `limits.yaml` so our envelope
      binds first, then verify a deliberately out-of-bounds command is
      REJECTED by us rather than clipped by the plugin (Day 2)
- [ ] Place the vendor URDF where the gate can hash it — copy or symlink to
      `b601/setup/urdf/b601_rs.urdf`, or set `B601_URDF`. Keep the vendor
      `meshes/` alongside it: placo resolves mesh paths against the URDF file
      and will not load without them (Day 2)
- [ ] Freeze pins: `bash b601/setup/pin_check.sh --record` (needs a committed,
      non-dirty lerobot checkout, and the URDF in place) (Day 2)
- [ ] Re-record pins after ANY URDF re-export — the model change moves every
      pose the safety layer checks, and is a registry event (Day 2 onward)
- [ ] Camera start, serial verification, calibration check (Day 3)
- [ ] `pin_check.sh` — expected output and what a failure means (Day 3)
- [ ] Workspace reset and object placement (Day 6)
- [ ] Start a single harness trial (Day 15)
- [ ] Read the result: where artifacts land, how to tell success from abort (Day 15)
- [ ] Recovery: what to do on a safety fault or hardware fault (Day 19)
- [ ] Cold-start rehearsal procedure (Day 19)
