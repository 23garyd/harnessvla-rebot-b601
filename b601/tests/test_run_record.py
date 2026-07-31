"""The run record must bind an episode to the physical state that produced it.

Two inherited defects are fixed here, both from copying the sim schema
unchanged (`b601/analysis/VENDORED.md`):

1. `run_meta` required RPent/LIBERO-shaped fields (`rpent_commit`, `suite`)
   that do not exist on this track — nothing here runs RPent — and required
   NOTHING physical. `pin_check.sh` gates camera serials and the calibration
   hash at launch, but the record it gates never stored them, so at Day 18 an
   episode could not be attributed to a camera configuration. That is the
   plan's "a changed camera invalidates affected episodes" with no way to tell
   which episodes.

2. There was no terminal status for a safety abort. `SafeDriver` latches a
   fault and stops; the run had to be filed as `valid_failure`, i.e. counted
   as a task the harness failed. The Day-18 gate reads "zero safety events"
   and the sim track's finding #5 is precisely that folding one terminal
   reason into another turns a weak claim into a strong-looking one.

Placeholder pin values are rejected on purpose. `UNKNOWN` is what the old
shell probes wrote when they failed, and a record that stores it is a record
that documents nothing while looking complete.
"""
import pytest

from b601.analysis.schemas import (VALIDITY_STATUSES, validate_result_row,
                                   validate_run_meta)

SHA = "a" * 64
COMMIT = "b" * 40


def meta(**over):
    m = {
        "exp_version": "v2",
        "condition": "harness",
        "task": "red_block_to_tray",
        "seed": 7,
        "planner_model": "claude-opus-5",
        "planner_settings": {"max_tokens": 8192},
        "prompt_hashes": {"system": "c" * 64},
        "repo_commit": COMMIT,
        "checkpoint_sha256": "d" * 64,
        "pins": {"lerobot_version": "0.1.0",
                 "camera_serials": "827312071234,918512070987",
                 "calibration_sha256": SHA},
        "budgets": {"max_steps": 300, "max_turns": 40, "max_wall_seconds": 600},
        "launch_command": "python -m b601.planner.run --task red_block_to_tray",
    }
    m.update(over)
    return m


def row(**over):
    r = {
        "success": True,
        "terminal_reason": "verified_release",
        "validity": "success",
        "counts": {"steps": 120, "turns": 9, "vla_act_calls": 1,
                   "analytic_calls": 6},
        "wall_seconds": 88.4,
    }
    r.update(over)
    return r


# --- run_meta: physical pins ---------------------------------------------

def test_valid_b601_run_meta_is_accepted():
    assert validate_run_meta(meta()) is not None


def test_run_meta_without_pins_is_rejected():
    """The defect: a record with no physical provenance validated clean."""
    m = meta()
    del m["pins"]
    with pytest.raises(ValueError, match="pins"):
        validate_run_meta(m)


@pytest.mark.parametrize("key", ["lerobot_version", "camera_serials",
                                 "calibration_sha256"])
def test_run_meta_missing_one_pin_is_rejected(key):
    m = meta()
    del m["pins"][key]
    with pytest.raises(ValueError, match=key):
        validate_run_meta(m)


@pytest.mark.parametrize("placeholder", ["UNKNOWN", "unknown", "MISSING", ""])
def test_placeholder_pin_value_is_rejected(placeholder):
    """What a failed probe used to write. A record that stores it documents
    nothing while looking complete."""
    with pytest.raises(ValueError, match="camera_serials"):
        validate_run_meta(meta(pins={**meta()["pins"],
                                     "camera_serials": placeholder}))


def test_calibration_hash_must_look_like_a_sha256():
    with pytest.raises(ValueError, match="calibration_sha256"):
        validate_run_meta(meta(pins={**meta()["pins"],
                                     "calibration_sha256": "abc123"}))


def test_camera_serials_must_be_canonically_ordered():
    """The ledger compares these as strings across runs; an unsorted list
    would read as camera drift when nothing physical changed."""
    with pytest.raises(ValueError, match="camera_serials"):
        validate_run_meta(meta(pins={**meta()["pins"],
                                     "camera_serials": "999,111"}))


def test_duplicate_camera_serial_is_rejected():
    with pytest.raises(ValueError, match="camera_serials"):
        validate_run_meta(meta(pins={**meta()["pins"],
                                     "camera_serials": "111,111"}))


def test_repo_commit_is_required():
    """Nothing here runs RPent; it is read for architecture only. The commit
    that matters is this repository's."""
    m = meta()
    del m["repo_commit"]
    with pytest.raises(ValueError, match="repo_commit"):
        validate_run_meta(m)


def test_sim_only_fields_are_not_required():
    """`rpent_commit` and `suite` are LIBERO concepts. Requiring them here
    would force every B601 record to carry a field it cannot fill honestly."""
    m = meta()
    assert "rpent_commit" not in m and "suite" not in m
    validate_run_meta(m)


# --- result_row: safety aborts -------------------------------------------

def test_safety_abort_is_a_terminal_status():
    assert "safety_abort" in VALIDITY_STATUSES


def test_safety_abort_row_is_accepted_with_evidence():
    validate_result_row(row(success=False, validity="safety_abort",
                            terminal_reason="workspace_violation",
                            evidence="SafetyViolation: pose outside workspace"))


def test_safety_abort_requires_evidence():
    """The latched fault reason. A safety event with no record of what
    tripped is not reviewable at the gate."""
    with pytest.raises(ValueError, match="evidence"):
        validate_result_row(row(success=False, validity="safety_abort",
                                terminal_reason="workspace_violation"))


def test_safety_abort_cannot_be_a_success():
    with pytest.raises(ValueError, match="inconsistent"):
        validate_result_row(row(success=True, validity="safety_abort",
                                evidence="latched fault"))
