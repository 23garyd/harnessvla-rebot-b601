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


# --- the interpreter is itself a pin --------------------------------------
#
# B601_PY is a legitimate override: the robot PC may deliberately run a managed
# environment rather than the repo venv. What is NOT legitimate is recording
# the pins under one interpreter and verifying them under another — the gate
# would then be comparing two different installations and calling it agreement.
# The interpreter was previously written into pins.env as a COMMENT, which
# `pin()` cannot read and verify never compared: recorded, but not gated.

def test_python_executable_probe_reports_the_running_interpreter():
    assert probe.python_executable() == sys.executable


def test_python_executable_is_not_resolved_through_symlinks():
    """A venv's python symlinks to the system interpreter. Resolving it would
    make two different environments report the same path."""
    assert probe.python_executable() == sys.executable
    assert "python-executable" in probe._PROBES


def pins_file(tmp_path, python_executable="/opt/conda/bin/python"):
    """A pins.env recorded under some other interpreter."""
    p = tmp_path / "pins.env"
    body = f"LEROBOT_VERSION=1.0\nLEROBOT_ORIGIN=pypi:lerobot:1.0\n" \
           f"CAMERA_SERIALS=111\nCALIBRATION_SHA256={'a' * 64}\n"
    if python_executable is not None:
        body = f"PYTHON_EXECUTABLE={python_executable}\n" + body
    p.write_text(body)
    return p


def test_verify_fails_when_the_interpreter_differs_from_the_recorded_one(tmp_path):
    r = run(f"bash {PIN_CHECK}", B601_PINS=str(pins_file(tmp_path)))
    assert r.returncode == 1
    assert "interpreter" in r.stderr
    assert "/opt/conda/bin/python" in r.stderr, "must name the recorded one"


def test_verify_fails_on_a_pins_file_recorded_before_the_interpreter_pin(tmp_path):
    """Back-compat is not silence: an older pins.env must be re-recorded, not
    verified against an unchecked interpreter."""
    r = run(f"bash {PIN_CHECK}",
            B601_PINS=str(pins_file(tmp_path, python_executable=None)))
    assert r.returncode == 1
    assert "PYTHON_EXECUTABLE" in r.stderr


def test_verify_fails_on_a_pins_file_recorded_before_the_origin_pin(tmp_path):
    """A version string cannot distinguish the Seeed lerobot fork from
    upstream. An older pins.env must be re-recorded, not verified against a
    codebase nothing identifies."""
    pins = tmp_path / "pins.env"
    pins.write_text(f"PYTHON_EXECUTABLE={sys.executable}\n"
                    f"LEROBOT_VERSION=1.0\nCAMERA_SERIALS=111\n"
                    f"CALIBRATION_SHA256={'a' * 64}\n")
    r = run(f"bash {PIN_CHECK}", B601_PINS=str(pins))
    assert r.returncode == 1
    assert "LEROBOT_ORIGIN" in r.stderr


def test_the_interpreter_is_checked_before_the_other_pins(tmp_path):
    """Cheapest and most fundamental: every other probe's answer depends on
    which interpreter produced it, so a mismatch must abort first."""
    r = run(f"bash {PIN_CHECK}", B601_PINS=str(pins_file(tmp_path)))
    assert "lerobot" not in r.stderr.lower()


def test_recorded_pins_carry_the_interpreter_as_a_gated_key(tmp_path):
    """It used to be a '# Recorded with interpreter:' comment, which pin()
    cannot read. A recorded-but-ungated value is not a pin."""
    calib = tmp_path / "calib.json"
    calib.write_text("{}")
    cameras = tmp_path / "cameras.json"
    cameras.write_text(json.dumps({"cameras": [{"serial": "111"}]}))
    pins = tmp_path / "pins.env"
    r = run(f"bash {PIN_CHECK} --record", B601_PINS=str(pins),
            B601_CALIB=str(calib), B601_CAMERAS=str(cameras))
    if r.returncode != 0:                    # lerobot is not installed here
        pytest.skip(f"record needs the full stack: {r.stderr.strip()}")
    assert f"PYTHON_EXECUTABLE={sys.executable}" in pins.read_text()


# --- pin_check: uses the repo interpreter, fails loudly -------------------

def test_pin_check_cannot_be_redirected_to_ambient_interpreter(tmp_path):
    r = run(
        f"bash {PIN_CHECK}",
        B601_PY="/nonexistent/ambient-python",
        B601_PINS=str(tmp_path / "absent.env"),
    )
    assert r.returncode == 1
    assert "no pins.env" in r.stderr
    assert "no repository interpreter" not in r.stderr


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


def test_setup_uses_distinct_bootstrap_interpreter_name():
    text = SETUP.read_text()
    assert "B601_BOOTSTRAP_PY" in text
    assert "B601_PY" not in text


def test_setup_has_no_stage_that_moves_the_robot():
    """Motion goes through tested primitives, never a setup script."""
    text = SETUP.read_text()
    for forbidden in ("move_to", "enable()", "set_gripper", "safe_home"):
        assert forbidden not in text, f"setup.sh must not call {forbidden}"
