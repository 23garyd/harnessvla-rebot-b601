"""The kinematic model is experiment state, like the cameras.

Every pose the safety layer checks — workspace containment, step distance,
home arrival — is forward kinematics over the URDF and the end-effector frame
named in it. Re-export the URDF, or point the solver at a different frame, and
all three move together and silently. That is the same failure the physical
regime already guards with CALIBRATION_SHA256; this is its model-side twin.

Also pinned here: the libraries that compute those poses. placo is not a
default dependency and only arrived with lerobot[kinematics], but it now
produces numbers a safety guard compares against, which makes its version
behaviour-affecting.
"""
import json

import pytest

from b601.setup import probe


class StubDist:
    def __init__(self, version, direct_url=None):
        self.version = version
        self._direct_url = direct_url

    def read_text(self, filename):
        if filename == "direct_url.json" and self._direct_url is not None:
            return json.dumps(self._direct_url)
        return None


# --- the URDF -------------------------------------------------------------

def test_urdf_hash_tracks_content(tmp_path):
    urdf = tmp_path / "arm.urdf"
    urdf.write_text("<robot name='a'/>")
    first = probe.urdf_sha256(urdf)
    urdf.write_text("<robot name='b'/>")
    assert probe.urdf_sha256(urdf) != first


def test_a_missing_urdf_raises_rather_than_returning_a_placeholder(tmp_path):
    with pytest.raises(probe.ProbeError, match="URDF"):
        probe.urdf_sha256(tmp_path / "absent.urdf")


def test_urdf_probe_is_registered():
    assert "urdf-sha256" in probe._PROBES


# --- the end-effector frame ----------------------------------------------

def test_ee_frame_is_read_from_the_driver_not_typed_twice():
    """A different frame is a different arm as far as every guard is
    concerned, so the pin has to track the value the driver actually uses."""
    from b601.driver.b601 import URDF_EE_FRAME
    assert probe.urdf_ee_frame() == URDF_EE_FRAME


def test_ee_frame_probe_is_registered():
    assert "urdf-ee-frame" in probe._PROBES


# --- the solver libraries -------------------------------------------------

def test_distribution_origin_is_available_generically():
    """One probe, three distributions: lerobot, placo, and the B601 plugin."""
    assert "distribution-origin" in probe._PROBES


def test_a_wheel_install_is_identified_by_name_and_version():
    assert probe.distribution_origin(
        "placo", dist=StubDist("0.9.6")) == "pypi:placo:0.9.6"


def test_a_forked_plugin_is_distinguishable_from_the_published_wheel():
    published = probe.distribution_origin(
        "lerobot-robot-seeed-b601", dist=StubDist("1.0.0"))
    forked = probe.distribution_origin(
        "lerobot-robot-seeed-b601", dist=StubDist("1.0.0", {
            "url": "https://github.com/someone/lerobot-robot-seeed-b601.git",
            "vcs_info": {"vcs": "git", "commit_id": "beef"}}))
    assert published != forked
    assert forked.endswith("@beef")


def test_the_generic_probe_passes_the_distribution_name_through():
    with pytest.raises(probe.ProbeError, match="no_such_distribution"):
        probe._PROBES["distribution-origin"]("no_such_distribution")


def test_the_generic_probe_requires_a_name():
    with pytest.raises(probe.ProbeError, match="distribution name"):
        probe._PROBES["distribution-origin"](None)
