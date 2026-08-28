"""The harness loop — the project's thesis, as a state machine.

    look -> stage -> invoke frozen policy -> lift -> verify -> branch:
        block in saucer            -> success
        held but not placed        -> deterministic place recovery
        not held                   -> re-ground and retry
    <= max_attempts, then graceful give-up.

Pure logic over an injected hardware object (`io`), so every branch runs
unpowered in the test suite; the live wiring supplies an io whose methods
move the real arm through the same rate-limited command stream as the
evaluation.

Fail-closed rules, each measured or bought with a prior failure:
- No block visible and saucer empty: give up and go home. Never guess.
- Staging refusal (beyond demonstrated coverage): refuse, go home.
- verify ONLY after lift_to_verify: a low hover beside an un-grasped block
  fools both verifier cues (eval eps 21/29, pixel-confirmed).
- Still held after one place recovery: give up as "stuck". No thrashing.
- Any hardware exception: abort with NO further motion commands — a
  faulted arm must not be commanded home blindly (2026-08-14 safety event:
  large discontinuous targets are how the arm got hurt).

The io contract:
    perceive_block() -> (x, y) | None   drift-gated agentview red blob
    block_in_saucer() -> bool           success check (30 px radius,
                                        calibrated: placed p95 15 px,
                                        nearest trial start 44 px)
    stage(pose)                         rate-limited move to staged pose
    invoke_policy()                     frozen primitive, time-budgeted
    lift_to_verify()                    move to the verify pose
    verify_frame() -> GraspVerdict      one wrist-frame + gripper sample
    place_recover()                     fixed place pose over saucer + open
    go_home()                           rate-limited return to park
"""
from __future__ import annotations

from dataclasses import dataclass

from b601.staging.table import StagingError


@dataclass(frozen=True)
class AttemptRecord:
    index: int
    pixel: tuple
    staging_distance_px: float
    held: bool
    reason: str


@dataclass(frozen=True)
class TrialResult:
    outcome: str          # "success" | "gave_up" | "refused" | "error_abort"
    attempts: tuple
    detail: str


class Harness:
    def __init__(self, table, io, max_attempts=3, verify_burst=5,
                 verify_majority=3, deep_table=None,
                 recovery_from_attempt=None):
        if not 0 < verify_majority <= verify_burst:
            raise ValueError("verify_majority must be in (0, verify_burst]")
        self._table = table
        # from this attempt number on, the HARNESS grasps (servo-centre,
        # descend, close) instead of re-invoking the policy. The policy
        # always gets attempt 1: the primitive is tried before the harness
        # takes over. None = policy every attempt (pre-recovery behaviour).
        self._recovery_from = recovery_from_attempt
        # retries stage from the AT-CLOSURE table when one is provided: after
        # a near-miss the policy gets the block practically in its fingers
        # (it is near-deterministic, so an identical retry repeats the miss)
        self._deep_table = deep_table
        self._io = io
        self._max_attempts = int(max_attempts)
        self._burst = int(verify_burst)
        self._majority = int(verify_majority)

    def _verify_held(self) -> bool:
        votes = sum(1 for _ in range(self._burst)
                    if self._io.verify_frame().held)
        return votes >= self._majority

    def run_trial(self) -> TrialResult:
        attempts = []
        try:
            return self._run(attempts)
        except Exception as exc:  # noqa: BLE001 — fail closed, no more motion
            return TrialResult("error_abort", tuple(attempts),
                               f"hardware fault, arm NOT homed: {exc}")

    def _finish(self, outcome, attempts, detail) -> TrialResult:
        self._io.go_home()
        return TrialResult(outcome, tuple(attempts), detail)

    def _run(self, attempts) -> TrialResult:
        io = self._io
        for i in range(1, self._max_attempts + 1):
            pixel = io.perceive_block()
            if pixel is None:
                if io.block_in_saucer():
                    return self._finish("success", attempts,
                                        "block in saucer (not on mat)")
                return self._finish("gave_up", attempts,
                                    "block not found on the mat")
            table = self._table if (i == 1 or self._deep_table is None) \
                else self._deep_table
            try:
                pose, dist = table.query(pixel[0], pixel[1])
            except StagingError as exc:
                return self._finish("refused", attempts,
                                    f"staging refused: {exc}")

            recovery = (self._recovery_from is not None
                        and i >= self._recovery_from)
            io.stage(pose)
            if recovery:
                io.recovery_grasp()
            else:
                io.invoke_policy()
            io.lift_to_verify()
            held = self._verify_held()

            if held:
                io.place_recover()
                io.lift_to_verify()
                if self._verify_held():
                    attempts.append(AttemptRecord(
                        i, tuple(pixel), float(dist), True,
                        "held after place recovery"))
                    return self._finish("gave_up", attempts,
                                        "block stuck in gripper — needs a human")
                reason = ("recovery grasped; placed" if recovery
                          else "grasped; placed by recovery")
            else:
                reason = ("recovery ran; gripper empty at verify" if recovery
                          else "policy ran; gripper empty at verify")

            attempts.append(AttemptRecord(i, tuple(pixel), float(dist),
                                          held, reason))
            if io.block_in_saucer():
                return self._finish("success", attempts,
                                    f"block in saucer after attempt {i}")
        return self._finish("gave_up", attempts,
                            f"{self._max_attempts} attempts exhausted")
