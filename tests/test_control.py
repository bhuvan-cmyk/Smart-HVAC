"""Unit tests for the control module.

These tests verify the pure control functions against the test vectors
defined in Section 5.8 of the specification. No I/O, no hardware.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from control import Controller, fan_percent, vent_percentages

# counts A,B,C,D -> vents A,B,C,D, fan
VECTORS = [
    ((0, 0, 0, 0), (0, 0, 0, 0), 0),
    ((0, 3, 0, 0), (15, 100, 15, 15), 44),
    ((0, 3, 0, 5), (15, 66, 15, 100), 84),
    ((1, 1, 1, 1), (100, 100, 100, 100), 52),
    ((0, 0, 0, 1), (15, 15, 15, 100), 28),
    ((12, 0, 0, 0), (100, 15, 15, 15), 100),
    ((1, 2, 0, 2), (58, 100, 15, 100), 60),
    ((5, 2, 1, 0), (100, 49, 32, 15), 84),
    ((7, 1, 0, 0), (100, 27, 15, 15), 84),
    ((10, 0, 0, 0), (100, 15, 15, 15), 100),
]


@pytest.mark.parametrize("counts, vents, fan", VECTORS)
def test_control_vectors(counts, vents, fan):
    assert vent_percentages(list(counts), max(counts)) == list(vents)
    assert fan_percent(sum(counts)) == fan


def test_half_up_rounding():
    # 15 + 85 * 1/2 = 57.5, which must round up to 58 (not banker's 58? 57.5 -> 58)
    assert vent_percentages([1, 2, 0, 2], 2)[0] == 58


def test_fan_table():
    expected = {0: 0, 1: 28, 3: 44, 4: 52, 5: 60, 8: 84, 10: 100, 12: 100}
    for total, pct in expected.items():
        assert fan_percent(total) == pct


def test_empty_room_holds_previous_outputs_then_idles():
    c = Controller()

    # People present: outputs follow the rule.
    state = c.update([0, 3, 0, 0], now=0.0)
    assert state == {"mode": "NORMAL", "vents": [15, 100, 15, 15], "fan": 44}

    # Zero counts but inside the 5 s hold: keep the last outputs.
    state = c.update([0, 0, 0, 0], now=1.0)
    assert state["mode"] == "NORMAL"
    assert state["vents"] == [15, 100, 15, 15]
    assert state["fan"] == 44

    # Still inside the hold (zero was first seen at t = 1.0).
    state = c.update([0, 0, 0, 0], now=5.9)
    assert state["mode"] == "NORMAL"
    assert state["vents"] == [15, 100, 15, 15]

    # Hold expired: IDLE, vents closed, fan at minimum PWM.
    state = c.update([0, 0, 0, 0], now=6.1)
    assert state == {"mode": "IDLE", "vents": [0, 0, 0, 0], "fan": 0}

    # Someone returns: normal control resumes immediately.
    state = c.update([1, 0, 0, 0], now=7.0)
    assert state["mode"] == "NORMAL"
    assert state["vents"] == [100, 15, 15, 15]
    assert state["fan"] == 28
