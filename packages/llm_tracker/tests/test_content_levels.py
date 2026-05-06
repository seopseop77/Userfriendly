"""Unit tests for the content-level ladder + per-mode ceiling table."""

import pytest
from llm_tracker.content_levels.levels import (
    ContentLevel,
    degrade,
    effective_ceiling,
)

# -- ladder ----------------------------------------------------------------


def test_ladder_is_strictly_ordered():
    assert ContentLevel.L0 < ContentLevel.L1 < ContentLevel.L2 < ContentLevel.L3


def test_ladder_int_values_match_documented_order():
    assert int(ContentLevel.L0) == 0
    assert int(ContentLevel.L3) == 3


# -- per-mode default ceiling ---------------------------------------------


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        ("L", ContentLevel.L1),
        ("A", ContentLevel.L0),
        ("R", ContentLevel.L1),
    ],
)
def test_default_ceiling_per_mode(mode, expected):
    assert effective_ceiling(mode) == expected


# -- opt-in elevation -----------------------------------------------------


def test_mode_R_opt_in_elevates_to_L3():
    assert effective_ceiling("R", user_opted_in=True) == ContentLevel.L3


@pytest.mark.parametrize("mode", ["L", "A"])
def test_opt_in_does_not_elevate_in_modes_without_consent_path(mode):
    assert effective_ceiling(mode, user_opted_in=True) == effective_ceiling(mode)


# -- unknown mode is a programming error ----------------------------------


def test_unknown_mode_raises():
    with pytest.raises(ValueError, match="unknown mode"):
        effective_ceiling("X")


# -- degrade --------------------------------------------------------------


@pytest.mark.parametrize(
    ("level", "ceiling", "expected"),
    [
        (ContentLevel.L3, ContentLevel.L0, ContentLevel.L0),
        (ContentLevel.L0, ContentLevel.L3, ContentLevel.L0),
        (ContentLevel.L2, ContentLevel.L2, ContentLevel.L2),
        (ContentLevel.L1, ContentLevel.L0, ContentLevel.L0),
    ],
)
def test_degrade_returns_min(level, ceiling, expected):
    assert degrade(level, ceiling) == expected


def test_degrade_never_elevates():
    assert degrade(ContentLevel.L0, ContentLevel.L3) == ContentLevel.L0
