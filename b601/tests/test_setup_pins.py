"""Pin-gate and setup-stage tests.

Regression coverage for three defects found in external review of the Day-0
scaffold (2026-07-31). The common root cause was a probe that degraded quietly
instead of failing, which is the one behaviour a gate must never have: if
--record and verify both degrade the same way, the gate compares UNKNOWN to
UNKNOWN and passes while checking nothing.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
PIN_CHECK = REPO / "b601" / "setup" / "pin_check.sh"
SETUP = REPO / "b601" / "setup" / "setup.sh"

sys.path.insert(0, str(REPO))
from b601.setup import probe  # noqa: E402


def run(cmd, **env):
    e = dict(os.environ)
    e.update(env)
    return subprocess.run(cmd, shell=True, capture_output=True, text=True,
                          env=e, cwd=str(REPO))


# --- probe: never returns a placeholder ----------------------------------

def test_missing_camera_manifest_raises_not_returns_unknown(tmp_path):
    """P1 root cause: the old shell probe fell back to `|| echo UNKNOWN`."""
    with pytest.raises(probe.ProbeError, match="manifest missing"):
        probe.camera_serials(tmp_path / "nope.json")


def test_camera_serials_are_sorted_and_joined(tmp_path):
    p = tmp_path / "cameras.json"
    p.write_text(json.dumps({"cameras": [{"serial": "222"}, {"serial": "111"}]}))
    assert probe.camera_serials(p) == "111,222"


def test_camera_manifest_is_anchored_not_cwd_relative(tmp_path, monkeypatch):
    """The old heredoc used __file__ inside `python - <<EOF`, where __file__ is
    '<stdin>', so the manifest resolved against the caller's cwd."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "cameras.json").write_text(
        json.dumps({"cameras": [{"serial": "DECOY"}]}))
    assert probe.DEFAULT_CAMERAS == REPO / "b601" / "setup" / "cameras.json"
    with pytest.raises(probe.ProbeError):        # the real anchor has no manifest
        probe.camera_serials()


@pytest.mark.parametrize("payload,match", [
    ('{"cameras": []}', "no cameras"),
    ('{"cameras": [{"model": "D405"}]}', "no serial"),
    ('{"cameras": [{"serial": "1"}, {"serial": "1"}]}', "duplicate"),
    ('not json', "malformed"),
    ('{"wrong_key": 1}', "malformed"),
])
def test_malformed_manifests_are_rejected(tmp_path, payload, match):
    p = tmp_path / "cameras.json"
    p.write_text(payload)
    with pytest.raises(probe.ProbeError, match=match):
        probe.camera_serials(p)


def test_calibration_sha_is_content_addressed(tmp_path):
    p = tmp_path / "calib.json"
    p.write_text("a")
    first = probe.calibration_sha256(p)
    p.write_text("b")
    assert probe.calibration_sha256(p) != first, "hash must track content"


def test_missing_calibration_raises(tmp_path):
    with pytest.raises(probe.ProbeError, match="calibration file missing"):
        probe.calibration_sha256(tmp_path / "nope.json")


def test_probe_cli_exits_nonzero_on_failure(tmp_path):
    assert probe.main(["camera-serials", str(tmp_path / "nope.json")]) == 1
    assert probe.main(["bogus-probe"]) == 64


# --- pin_check: uses the repo interpreter, fails loudly -------------------

def test_pin_check_refuses_an_ambient_interpreter():
    """P1: with no repo venv, pin_check must refuse rather than silently probe
    whatever `python` happens to be on PATH (here: an unrelated conda env)."""
    r = run(f"bash {PIN_CHECK}", B601_PY="/nonexistent/python")
    assert r.returncode == 1
    assert "no repository interpreter" in r.stderr


def test_pin_check_aborts_when_a_probe_fails(tmp_path):
    """A failed probe must abort, never record or compare a placeholder."""
    pins = tmp_path / "pins.env"
    pins.write_text("LEROBOT_VERSION=1.0\nCAMERA_SERIALS=1\nCALIBRATION_SHA256=x\n")
    r = run(f"bash {PIN_CHECK}", B601_PINS=str(pins),
            B601_CAMERAS=str(tmp_path / "nope.json"))
    assert r.returncode == 1
    assert "PROBE FAILED" in r.stderr or "FATAL" in r.stderr
    assert "UNKNOWN" not in (tmp_path / "pins.env").read_text()


def test_pin_check_without_pins_file_fails_clearly(tmp_path):
    r = run(f"bash {PIN_CHECK}", B601_PINS=str(tmp_path / "absent.env"))
    assert r.returncode == 1
    assert "no pins.env" in r.stderr


def test_pin_check_rejects_unknown_argument():
    r = run(f"bash {PIN_CHECK} --bogus")
    assert r.returncode == 64
    assert "usage" in r.stderr


# --- setup stages: dependency is enforced, not implied --------------------

@pytest.mark.parametrize("stage", ["verify", "hardware"])
def test_stage_without_env_gives_an_actionable_error_not_127(stage, tmp_path):
    """P2: previously exited 127 with 'No such file or directory'."""
    r = run(f"bash {SETUP} {stage}", B601_REPO=str(tmp_path))
    assert r.returncode == 1, f"expected clean failure, got {r.returncode}"
    assert "run 'bash b601/setup/setup.sh env' first" in r.stderr


def test_setup_rejects_unknown_stage():
    r = run(f"bash {SETUP} bogus")
    assert r.returncode == 64
    assert "usage" in r.stderr


def test_setup_has_no_stage_that_moves_the_robot():
    """Motion goes through tested primitives, never a setup script."""
    text = SETUP.read_text()
    for forbidden in ("move_to", "enable()", "set_gripper", "safe_home"):
        assert forbidden not in text, f"setup.sh must not call {forbidden}"
