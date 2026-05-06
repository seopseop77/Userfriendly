"""Unit tests for the mode-by-mode capability policy table."""

import pytest
from llm_tracker.plugin_host.policy import (
    MODE_DENIED_CAPABILITIES,
    denied_capabilities,
)
from llm_tracker_sdk.capabilities import (
    ALL_CAPABILITIES,
    EGRESS_HTTP,
)

# -- table shape -----------------------------------------------------------


def test_policy_table_covers_all_modes():
    assert set(MODE_DENIED_CAPABILITIES.keys()) == {"L", "A", "R"}


def test_only_egress_http_denied_in_mode_L():
    assert MODE_DENIED_CAPABILITIES["L"] == frozenset({EGRESS_HTTP})


@pytest.mark.parametrize("mode", ["A", "R"])
def test_modes_A_and_R_have_no_load_time_denials(mode):
    assert MODE_DENIED_CAPABILITIES[mode] == frozenset()


# -- denied_capabilities(): per-(mode, capability) matrix ------------------


@pytest.mark.parametrize("capability", sorted(ALL_CAPABILITIES))
@pytest.mark.parametrize("mode", ["L", "A", "R"])
def test_each_capability_under_each_mode(mode, capability):
    """`egress_http` is denied only in Mode L; everything else is allowed everywhere."""
    expected_denied = {EGRESS_HTTP} if (mode == "L" and capability == EGRESS_HTTP) else set()
    assert denied_capabilities(mode, [capability]) == frozenset(expected_denied)


def test_multiple_declared_returns_only_the_denied_subset():
    declared = ["read_request_metadata", EGRESS_HTTP, "modify_request"]
    assert denied_capabilities("L", declared) == frozenset({EGRESS_HTTP})


def test_empty_declared_is_always_allowed():
    assert denied_capabilities("L", []) == frozenset()
    assert denied_capabilities("R", []) == frozenset()


def test_unknown_mode_raises():
    with pytest.raises(ValueError, match="unknown mode"):
        denied_capabilities("X", [EGRESS_HTTP])
