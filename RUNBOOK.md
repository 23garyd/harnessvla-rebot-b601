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
- [x] **Camera manifest and serial verification (Day 3).** The manifest is data,
      validated on load; `probe.camera_serials` reads the same file:
      ```
      PYTHONPATH= .venv/bin/python -c "from b601.cameras.config import *; print(load_cameras())"
      PYTHONPATH= .venv/bin/python -m b601.setup.probe camera-serials
      #   expect: 353322271941,DSJ-250318-J
      ```
      Both cameras must negotiate **640x480 @ 30** — the only mode both reach on
      their current links. The top camera has no 15 fps MJPG mode, and the D405
      is on USB 2.1, which fits colour but not colour plus depth. Address the
      top camera by its `/dev/v4l/by-id/...` path, never `/dev/video0`, which
      renumbers across reboots.
- [x] **PREFLIGHT — the one command to run before every recording session.**
      ```
      PYTHONNOUSERSITE=1 PYTHONPATH=$PWD \
        /home/demo/miniforge3/envs/lerobot/bin/python -m b601.cameras.preflight
      #   exit 0 = safe to record, 1 = do not record yet
      ```
      Applies the manifest, verifies the negotiated modes, confirms every
      camera is DELIVERING FRAMES, checks timing, and checks the mounts have
      not drifted — in that order, and in one exit code. The individual tools
      below are still there for diagnosis when it fails.

      Reference numbers on the current topology (both cameras USB 2, separate
      controllers), 60 frames each:
      `agentview` mean 33.29 ms / jitter p95 2.74 ms, `eye_in_hand` mean
      33.30 ms / jitter p95 0.10 ms, 0 dropped, pairing gap p95 17.7 ms.
      **The pairing gap sits at 0.53 of a frame period, near its structural
      maximum** — nearest-timestamp pairing between free-running cameras is
      bounded by half a period plus jitter, so this is expected, not
      degradation. The tolerance is 0.6 periods, so the margin is thin by
      design rather than by accident.
- [ ] **Timestamp sync check — component tool, run standalone to diagnose.**
      ```
      PYTHONPATH= .venv/bin/python -m b601.cameras.sync <timestamps.json>
      #   exit 0 clean, 1 not. Omit "fps" from the file and it checks against
      #   the manifest's declared rate rather than one retyped by hand.
      ```
      Reference numbers from 2026-08-06, 150 frames per camera: jitter p95
      3.12 ms (`agentview`) and 0.22 ms (`eye_in_hand`), 0 dropped, 9.04 ms p95
      pairing gap. **A large `max` jitter with a small p95 is normal** — it is
      buffered frames flushing at stream start.
      **The index-paired offset in the report is a diagnostic, not a fault.**
      The cameras drift 0.28 ms/frame because they are free-running; the
      recorder must pair frames by timestamp, never by frame index.
- [x] **Apply the manifest to the cameras — run before EVERY session (Day 3).**
      Recording the fixed values in `cameras.json` is not applying them. This
      writes them and reads every one back, because a write to an inactive
      V4L2 control succeeds and does nothing:
      ```
      PYTHONNOUSERSITE=1 PYTHONPATH=$PWD \
        /home/demo/miniforge3/envs/lerobot/bin/python -m b601.cameras.capture
      #   exit 0 = every recorded setting written AND verified
      ```
      Run it per session, not once by hand: a replug or a `hardware_reset()`
      restores defaults. Verified end to end on 2026-08-06 — reset both cameras
      to auto, applied, confirmed from an independent process.
      **It does not open a stream**, so it cannot tell you the camera is
      actually delivering frames. See the next item.
- [x] **The D405 streams exactly ONE pipeline session per hardware reset.**
      Root-caused 2026-08-07 (fw 5.12.14.100, on USB 3.2, raw pyrealsense2 —
      no LeRobot code involved): after a reset the first pipeline session
      delivers every frame; the second and every later one opens fine,
      negotiates the right profile, and delivers **nothing**, no matter how
      long you wait. This is why a passing check can kill the recording that
      follows it. Every consumer of a session must be preceded by
      ```
      PYTHONNOUSERSITE=1 PYTHONPATH=$PWD \
        /home/demo/miniforge3/envs/lerobot/bin/python -m b601.cameras.reset
      ```
      followed by `-m b601.cameras.capture`, because the reset restores auto
      exposure. `record_session.sh` does both, twice (before preflight, and
      again before `lerobot-record`). Setting options WITHOUT a pipeline does
      not consume the session. If you ran ANY camera check by hand, the D405
      is dead until the next reset — that is normal, not a fault. Candidate
      real fix: a firmware update (owner decision, see risk_log.md).
      Separately: the vendor wrapper's colour-only path delivered zero frames
      even on a good session until vendor commit `3b4f877` (null-frame check
      used `is not None`; null frames are falsy, never None).
- [ ] **Mount drift check — run at the START of every session (Day 3).**
      Not a calibration: it detects that a mount MOVED, which is the failure
      that silently biases every episode recorded afterwards.
      ```
      # once, with the cameras in their FINAL position and ArUco markers placed:
      PYTHONNOUSERSITE=1 PYTHONPATH=$PWD \
        /home/demo/miniforge3/envs/lerobot/bin/python -m b601.cameras.reference --record
      # thereafter, before recording anything:
      PYTHONNOUSERSITE=1 PYTHONPATH=$PWD \
        /home/demo/miniforge3/envs/lerobot/bin/python -m b601.cameras.reference
      #   exit 0 clean, 1 if a mount moved
      ```
      Markers must be `DICT_4X4_50`, fixed to the same structure as the
      workspace, and OUTSIDE the area objects move through — the check cannot
      tell a moved camera from a moved marker.
      `eye_in_hand` reports **NOT CHECKED** and that is correct: a wrist
      camera's landmarks move with the arm, so its reference needs a repeatable
      arm pose that does not exist until `safe_home` is trusted.
      Re-recording redefines "not drifted" — registry event, and
      `CALIBRATION_SHA256` must be re-recorded with it.
- [ ] Set `eye_in_hand.exposure` from measurement under workspace lighting, and
      confirm the fingers are resolvable at that exposure (Day 3). The 8000 us
      in the manifest is a placeholder; the camera's own auto-selected 33000 us
      is a full frame period at 30 fps and would blur every wrist frame.
- [ ] `pin_check.sh` — expected output and what a failure means (Day 3).
      **Two blockers today:** `--record` is all-or-nothing and probes the
      calibration file, which does not exist until calibration is done; and the
      script hardcodes `.venv/bin/python` while the robot-facing environment is
      the conda env `lerobot`. Resolve the interpreter question before
      recording, or episodes cannot be attributed to a configuration.
- [ ] Workspace reset and object placement (Day 6)
- [ ] Start a single harness trial (Day 15)
- [ ] Read the result: where artifacts land, how to tell success from abort (Day 15)
- [ ] Recovery: what to do on a safety fault or hardware fault (Day 19)
- [ ] Cold-start rehearsal procedure (Day 19)
