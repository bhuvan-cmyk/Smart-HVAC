"""Unit tests for zone assignment and median smoothing.

Tests feet-point assignment by quadrant, shared boundaries, points outside
every polygon, and the median filter used for per-zone counts.
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from zones import MedianSmoother, Zones


@pytest.mark.parametrize(
    "box, zone",
    [
        ((0.20, 0.10, 0.30, 0.25), "A"),
        ((0.70, 0.10, 0.80, 0.25), "B"),
        ((0.20, 0.70, 0.30, 0.85), "C"),
        ((0.70, 0.70, 0.80, 0.85), "D"),
    ],
)
def test_quadrants(box, zone):
    assert Zones().assign(*box) == zone


def test_feet_point_not_box_centre():
    # A tall box whose centre is in A but whose feet are in C.
    assert Zones().assign(0.40, 0.10, 0.60, 0.80) == "C"


def test_shared_boundary_belongs_to_first_zone():
    # Feet x is exactly 0.5, the A/B split; A is tested first.
    assert Zones().assign(0.45, 0.10, 0.55, 0.20) == "A"


def test_outside_every_polygon_is_unzoned(tmp_path):
    zones_file = tmp_path / "zones.json"
    zones_file.write_text(
        json.dumps(
            {
                "A": [[0.0, 0.0], [0.2, 0.0], [0.2, 0.2], [0.0, 0.2]],
                "B": [[0.8, 0.0], [1.0, 0.0], [1.0, 0.2], [0.8, 0.2]],
                "C": [[0.0, 0.8], [0.2, 0.8], [0.2, 1.0], [0.0, 1.0]],
                "D": [[0.8, 0.8], [1.0, 0.8], [1.0, 1.0], [0.8, 1.0]],
            }
        ),
        encoding="utf-8",
    )
    zones = Zones(zones_json_path=str(zones_file))
    assert zones.assign(0.40, 0.40, 0.60, 0.60) == "U"
    assert zones.assign(0.05, 0.05, 0.15, 0.15) == "A"
    counts = zones.assign_detections(
        [
            {"x1": 0.40, "y1": 0.40, "x2": 0.60, "y2": 0.60},
            {"x1": 0.85, "y1": 0.85, "x2": 0.95, "y2": 0.95},
        ]
    )
    assert counts == {"A": 0, "B": 0, "C": 0, "D": 1, "U": 1}


def test_median_ignores_single_outlier():
    smoother = MedianSmoother(window=5)
    assert smoother.update(2) == 2
    assert smoother.update(2) == 2
    assert smoother.update(100) == 2
    assert smoother.update(2) == 2
    assert smoother.update(2) == 2


def test_median_rounds_half_up():
    # Four samples: median is (2 + 3) / 2 = 2.5, rounded half-up to 3.
    smoother = MedianSmoother(window=4)
    for value in (1, 2, 3, 100):
        result = smoother.update(value)
    assert result == 3
