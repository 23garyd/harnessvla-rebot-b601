"""The lerobot pin must identify a CODEBASE, not a version string.

The vendor's own instructions install a fork — `git clone
Seeed-Projects/lerobot` then `pip install -e ./lerobot` — and explicitly warn
against upstream HuggingFace. Two consequences the version pin cannot see:

  A fork reports the same `__version__` as upstream. `0.4.x == 0.4.x` passes
  the gate while a different codebase is running.

  An editable install has no version movement at all. `git pull` in that clone
  changes joint direction conventions, unit handling, limit defaults or the
  dataset schema, and `LEROBOT_VERSION` does not move a digit.

The blast radius is data, not motion: episodes recorded under an unidentified
stack cannot be attributed afterwards, and teleop episodes are irreplaceable
(risk log). So this must land before the first pilot episode, not before
evaluation.

An uncommitted working tree is REFUSED rather than recorded. A dirty tree
recorded as dirty and verified as dirty compares equal while the content
differs — the exact "gate passes while checking nothing" shape this file's
neighbours exist to prevent.
"""
import json

import pytest

from b601.setup import probe


class StubDist:
    def __init__(self, direct_url=None, version="0.4.1"):
        self._direct_url = direct_url
        self.version = version

    def read_text(self, filename):
        if filename == "direct_url.json" and self._direct_url is not None:
            return json.dumps(self._direct_url)
        return None


def head(commit="abc123", dirty=False):
    return lambda path: (commit, dirty)


# --- installed from an index ---------------------------------------------

def test_a_registry_install_is_identified_by_name_and_version():
    origin = probe.distribution_origin(
        "lerobot", dist=StubDist(version="0.4.1"), git_head=head())
    assert origin == "pypi:lerobot:0.4.1"


# --- installed from git ---------------------------------------------------

def test_a_vcs_install_records_the_url_and_commit():
    origin = probe.distribution_origin("lerobot", dist=StubDist({
        "url": "https://github.com/Seeed-Projects/lerobot.git",
        "vcs_info": {"vcs": "git", "commit_id": "d34db33f"},
    }), git_head=head())
    assert origin == "git+https://github.com/Seeed-Projects/lerobot.git@d34db33f"


def test_the_fork_is_distinguishable_from_upstream():
    """The whole point: same version, different codebase, different pin."""
    seeed = probe.distribution_origin("lerobot", dist=StubDist({
        "url": "https://github.com/Seeed-Projects/lerobot.git",
        "vcs_info": {"vcs": "git", "commit_id": "aaa"}}), git_head=head())
    upstream = probe.distribution_origin("lerobot", dist=StubDist({
        "url": "https://github.com/huggingface/lerobot.git",
        "vcs_info": {"vcs": "git", "commit_id": "aaa"}}), git_head=head())
    assert seeed != upstream


# --- editable install (what the vendor wiki actually tells you to do) ------

def test_an_editable_install_is_pinned_by_its_git_head():
    """PEP 610 records only the directory for `pip install -e .`; the commit
    has to come from the source tree, or the pin moves with nothing."""
    origin = probe.distribution_origin("lerobot", dist=StubDist({
        "url": "file:///home/demo/rebot_lerobot/lerobot",
        "dir_info": {"editable": True},
    }), git_head=head("feedface"))
    assert origin == "editable+git:feedface"


def test_an_editable_install_with_uncommitted_changes_is_refused():
    """Recording 'dirty' then verifying 'dirty' compares equal while the code
    differs. An unpinnable tree must abort, not be written down."""
    with pytest.raises(probe.ProbeError, match="uncommitted"):
        probe.distribution_origin("lerobot", dist=StubDist({
            "url": "file:///home/demo/rebot_lerobot/lerobot",
            "dir_info": {"editable": True},
        }), git_head=head("feedface", dirty=True))


def test_an_editable_install_outside_git_is_refused():
    def no_git(path):
        raise probe.ProbeError(f"not a git working tree: {path}")

    with pytest.raises(probe.ProbeError, match="git"):
        probe.distribution_origin("lerobot", dist=StubDist({
            "url": "file:///opt/lerobot",
            "dir_info": {"editable": True},
        }), git_head=no_git)


# --- a local non-editable directory install -------------------------------

def test_a_local_directory_install_is_pinned_by_its_git_head():
    origin = probe.distribution_origin("lerobot", dist=StubDist({
        "url": "file:///home/demo/lerobot",
    }), git_head=head("c0ffee"))
    assert origin == "local+git:c0ffee"


# --- absent -------------------------------------------------------------

def test_a_missing_distribution_raises_rather_than_returning_a_placeholder():
    def missing(name):
        raise probe.ProbeError(f"distribution {name!r} is not installed")

    with pytest.raises(probe.ProbeError, match="not installed"):
        probe.distribution_origin("lerobot", dist=None, find=missing)


def test_the_probe_is_registered_on_the_cli():
    assert "lerobot-origin" in probe._PROBES
