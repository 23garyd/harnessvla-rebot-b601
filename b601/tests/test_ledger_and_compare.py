"""Ledger and paired comparison, on B601-shaped records.

Three inherited problems are covered here:

1. `build_ledger` imported `track.analysis.schemas` — the SIM repo's package
   path. The vendored copy could not be imported at all in this repo, so
   nothing that depends on it had ever run.

2. Its columns carried `suite` and `rpent_commit` (LIBERO concepts) and no
   physical state. The ledger is the input to every Day-18 number; if the
   camera configuration is not a column, no analysis can group by it.

3. `compare.paired_table` dropped only `infra_failure`. A safety abort would
   have been scored as an ordinary task failure — the Day-18 gate reads "zero
   safety events", so it must be counted and shown, never averaged in.
"""
import json

import pytest

from b601.analysis.build_ledger import LEDGER_COLUMNS, build_ledger
from b601.analysis.compare import paired_table, render_markdown

PINS = {"lerobot_version": "0.1.0",
        "camera_serials": "111,222",
        "calibration_sha256": "a" * 64}


def write_run(root, condition, task, seed, *, validity="success",
              success=True, ts="20260731T100000", **result_extra):
    run_dir = root / "v2" / condition / task / str(seed) / ts
    run_dir.mkdir(parents=True)
    (run_dir / "run_meta.json").write_text(json.dumps({
        "exp_version": "v2", "condition": condition, "task": task,
        "seed": seed, "planner_model": "claude-opus-5",
        "planner_settings": {}, "prompt_hashes": {"system": "c" * 64},
        "repo_commit": "b" * 40, "checkpoint_sha256": "d" * 64,
        "pins": PINS,
        "budgets": {"max_steps": 300, "max_turns": 40,
                    "max_wall_seconds": 600},
        "launch_command": "python -m b601.planner.run",
    }))
    (run_dir / "result_row.json").write_text(json.dumps({
        "success": success, "terminal_reason": validity, "validity": validity,
        "counts": {"steps": 10, "turns": 3, "vla_act_calls": 1,
                   "analytic_calls": 4},
        "wall_seconds": 42.0, **result_extra,
    }))
    return run_dir


# --- ledger ---------------------------------------------------------------

def test_ledger_builds_from_b601_run_dirs(tmp_path):
    """It could not even import before this; nothing downstream had run."""
    write_run(tmp_path, "harness", "red_block_to_tray", 7)
    rows, skipped_seed0, incomplete = build_ledger(tmp_path)
    assert (len(rows), skipped_seed0, incomplete) == (1, 0, 0)
    assert rows[0]["task"] == "red_block_to_tray"


def test_ledger_carries_the_physical_pins(tmp_path):
    """Without these columns, no Day-18 number can be attributed to a camera
    configuration or a calibration."""
    write_run(tmp_path, "harness", "red_block_to_tray", 7)
    rows, _, _ = build_ledger(tmp_path)
    assert rows[0]["camera_serials"] == "111,222"
    assert rows[0]["calibration_sha256"] == "a" * 64
    assert rows[0]["lerobot_version"] == "0.1.0"
    assert rows[0]["repo_commit"] == "b" * 40
    for column in ("camera_serials", "calibration_sha256", "lerobot_version",
                   "repo_commit"):
        assert column in LEDGER_COLUMNS


def test_ledger_has_no_sim_only_columns():
    assert "suite" not in LEDGER_COLUMNS
    assert "rpent_commit" not in LEDGER_COLUMNS


def test_seed_zero_is_never_scored(tmp_path):
    write_run(tmp_path, "harness", "red_block_to_tray", 0)
    rows, skipped_seed0, _ = build_ledger(tmp_path)
    assert (rows, skipped_seed0) == ([], 1)


def test_a_record_missing_its_pins_stops_the_build(tmp_path):
    run_dir = write_run(tmp_path, "harness", "red_block_to_tray", 7)
    meta = json.loads((run_dir / "run_meta.json").read_text())
    del meta["pins"]
    (run_dir / "run_meta.json").write_text(json.dumps(meta))
    with pytest.raises(ValueError, match="pins"):
        build_ledger(tmp_path)


# --- paired comparison ----------------------------------------------------

def ledger_row(condition, task, seed, success, validity="success"):
    return {"condition": condition, "task": task, "seed": seed,
            "success": success, "validity": validity}


def test_safety_abort_is_not_scored_as_a_task_failure():
    """It would otherwise count against the harness arm as an ordinary miss."""
    rows = [
        ledger_row("direct", "t", 1, 1),
        ledger_row("harness", "t", 1, 0, "safety_abort"),
    ]
    table = paired_table(rows)
    assert table["aggregate"]["harness"]["n"] == 0
    assert table["safety_aborts"] == [("t", 1, "harness")]


def test_safety_aborts_are_reported_even_when_there_are_none():
    """The Day-18 gate is 'zero safety events' — the zero must be shown, not
    inferred from an absent line."""
    rows = [ledger_row("direct", "t", 1, 1), ledger_row("harness", "t", 1, 1)]
    table = paired_table(rows)
    assert table["safety_aborts"] == []
    assert "0 safety aborts" in render_markdown(table)


def test_safety_abort_is_named_in_the_rendered_table():
    rows = [
        ledger_row("direct", "t", 1, 1),
        ledger_row("harness", "t", 1, 0, "safety_abort"),
    ]
    out = render_markdown(paired_table(rows))
    assert "1 safety abort" in out
    assert "('t', 1, 'harness')" in out


def test_infra_failures_are_still_excluded():
    rows = [
        ledger_row("direct", "t", 1, 1),
        ledger_row("harness", "t", 1, 0, "infra_failure"),
    ]
    table = paired_table(rows)
    assert table["aggregate"]["harness"]["n"] == 0
    assert table["safety_aborts"] == []


def test_an_all_excluded_table_renders_instead_of_crashing():
    """Inherited: summarize() called wilson_interval(0, 0), which raises. A
    Day-18 rebuild where exclusions remove every pair must still produce a
    table saying so."""
    rows = [
        ledger_row("direct", "t", 1, 0, "safety_abort"),
        ledger_row("harness", "t", 1, 0, "safety_abort"),
    ]
    out = render_markdown(paired_table(rows))
    assert "0/0 [no scored pairs]" in out
    assert "2 safety aborts" in out


def test_complete_pairs_still_score_normally():
    rows = [
        ledger_row("direct", "t", 1, 0),
        ledger_row("harness", "t", 1, 1),
        ledger_row("direct", "t", 2, 1),
        ledger_row("harness", "t", 2, 1),
    ]
    table = paired_table(rows)
    assert table["aggregate"]["direct"]["k"] == 1
    assert table["aggregate"]["harness"]["k"] == 2
    assert table["flips"]["rescued"] == 1
