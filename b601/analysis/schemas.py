"""Validation for the two track-added run records (spec section 3).

run_meta.json  - written at launch, immutable.
result_row.json - written at termination; the only input to the ledger.
Extra/unknown keys are intentionally permitted (forward compatibility).

DIVERGED FROM THE SIM COPY (see VENDORED.md). Two changes, both because this
track runs on hardware:

  physical pins are required.  The sim run only had to identify software. Here
  the camera serials and the calibration hash ARE experiment state — the plan
  is explicit that a changed camera invalidates affected episodes — so the
  record that pin_check.sh gates must also store what it gated on. Without
  that, Day-18 analysis cannot attribute an episode to a configuration.

  safety_abort is a terminal status.  SafeDriver latches a fault and stops.
  Filing that as valid_failure counts a safety event as a task the harness
  failed, and the Day-18 gate reads "zero safety events". The sim track's
  finding #5 is exactly this: a rate that silently absorbs one terminal reason
  is not measuring what it claims.

Pin values are checked for shape, not just presence. `UNKNOWN` is what the old
shell probes emitted on failure, and a record storing it looks complete while
documenting nothing.
"""
import math

VALIDITY_STATUSES = {
    "success",
    "valid_failure",
    "infra_failure",
    "safety_abort",
    "timeout",
    "budget_exhausted",
}

# Statuses that are not scored outcomes: each needs evidence a human can read
# at a gate, and each is reported separately rather than averaged in.
EVIDENCE_REQUIRED = {"infra_failure", "safety_abort"}

_PLACEHOLDERS = {"unknown", "missing", "todo", "none", "n/a"}

_RUN_META_REQUIRED = {
    "exp_version": str,
    "condition": str,
    "task": str,
    "seed": int,
    "planner_model": str,
    "planner_settings": dict,
    "prompt_hashes": dict,
    "repo_commit": str,
    "checkpoint_sha256": str,
    "pins": dict,
    "budgets": dict,
    "launch_command": str,
}

# Mirrors b601/setup/pins.env, lower-cased. pin_check.sh gates these at
# launch; this is where they are recorded against the episode.
_PINS_REQUIRED = {
    "lerobot_version": str,
    "camera_serials": str,
    "calibration_sha256": str,
}

_BUDGETS_REQUIRED = {
    "max_steps": int,
    "max_turns": int,
    "max_wall_seconds": int,
}

_RESULT_ROW_REQUIRED = {
    "success": bool,
    "terminal_reason": str,
    "validity": str,
    "counts": dict,
    "wall_seconds": (int, float),
}

_COUNTS_REQUIRED = {
    "steps": int,
    "turns": int,
    "vla_act_calls": int,
    "analytic_calls": int,
}


def _require(record, spec, where):
    if not isinstance(record, dict):
        raise ValueError(f"{where}: expected dict, got {type(record).__name__}")
    for key, typ in spec.items():
        if key not in record:
            raise ValueError(f"{where}: missing required key '{key}'")
        if not isinstance(record[key], typ) or (
            typ is int and isinstance(record[key], bool)
        ):
            raise ValueError(
                f"{where}: key '{key}' must be {typ}, "
                f"got {type(record[key]).__name__}"
            )


def _is_hex(value, length):
    return len(value) == length and all(c in "0123456789abcdefABCDEF"
                                        for c in value)


def _require_substantive(value, where):
    """Reject blanks and the placeholders a failed probe used to write."""
    if not value.strip():
        raise ValueError(f"{where}: is empty")
    if value.strip().lower() in _PLACEHOLDERS:
        raise ValueError(
            f"{where}: is the placeholder '{value}' — a failed probe was "
            f"recorded as if it were a pin; re-run pin_check.sh")


def _validate_pins(pins):
    _require(pins, _PINS_REQUIRED, "run_meta.pins")
    for key in _PINS_REQUIRED:
        _require_substantive(pins[key], f"run_meta.pins.{key}")

    calib = pins["calibration_sha256"]
    if not _is_hex(calib, 64):
        raise ValueError(
            f"run_meta.pins.calibration_sha256: not a sha256 digest: {calib!r}")

    serials = pins["camera_serials"].split(",")
    if any(not s.strip() for s in serials):
        raise ValueError(
            f"run_meta.pins.camera_serials: empty entry in "
            f"{pins['camera_serials']!r}")
    if len(set(serials)) != len(serials):
        raise ValueError(
            f"run_meta.pins.camera_serials: duplicate serial in "
            f"{pins['camera_serials']!r}")
    if serials != sorted(serials):
        # The ledger compares this string across runs; an unsorted list would
        # read as camera drift when nothing physical changed. probe.py sorts.
        raise ValueError(
            f"run_meta.pins.camera_serials: not sorted: "
            f"{pins['camera_serials']!r}")


def validate_run_meta(meta):
    _require(meta, _RUN_META_REQUIRED, "run_meta")
    _require(meta["budgets"], _BUDGETS_REQUIRED, "run_meta.budgets")
    _validate_pins(meta["pins"])
    for key in ("repo_commit", "checkpoint_sha256"):
        _require_substantive(meta[key], f"run_meta.{key}")
    if not _is_hex(meta["repo_commit"], 40):
        raise ValueError(
            f"run_meta.repo_commit: expected a full 40-character git sha, "
            f"got {meta['repo_commit']!r}")
    return meta


def validate_result_row(row):
    _require(row, _RESULT_ROW_REQUIRED, "result_row")
    _require(row["counts"], _COUNTS_REQUIRED, "result_row.counts")
    for key in _COUNTS_REQUIRED:
        if row["counts"][key] < 0:
            raise ValueError(
                f"result_row.counts: key '{key}' must be >= 0, "
                f"got {row['counts'][key]}"
            )
    ws = row["wall_seconds"]
    if isinstance(ws, bool) or not math.isfinite(ws) or ws < 0:
        raise ValueError(
            f"result_row: wall_seconds must be a finite number >= 0, got {ws!r}"
        )
    if row["validity"] not in VALIDITY_STATUSES:
        raise ValueError(
            f"result_row: unknown validity '{row['validity']}', "
            f"expected one of {sorted(VALIDITY_STATUSES)}"
        )
    if row["success"] != (row["validity"] == "success"):
        raise ValueError(
            "result_row: success flag inconsistent with validity "
            f"(success={row['success']}, validity='{row['validity']}')"
        )
    if row["validity"] in EVIDENCE_REQUIRED:
        evidence = row.get("evidence")
        if not isinstance(evidence, str) or not evidence.strip():
            raise ValueError(
                f"result_row: {row['validity']} requires non-empty 'evidence' "
                "(infra: crash log, missing artifact; safety_abort: the "
                "latched SafeDriver fault reason)"
            )
    return row
