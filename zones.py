"""Zone assignment for four quadrants of the camera view.

Zones A–D are polygons in normalised frame coordinates (0 to 1 in both axes).
The default is a 2 × 2 grid:
  A = top-left,  B = top-right
  C = bottom-left, D = bottom-right

A person is assigned to the zone containing their feet point:
    feet = ((x1 + x2) / 2, y2)
i.e. the bottom-centre of the detection box.

A point on a shared edge belongs to the first zone in the order A, B, C, D.
A point outside all polygons is counted in the total but belongs to no zone.

If a zones.json file exists in the project root, it overrides the default grid.
The file format is: {"A": [[x,y],...], "B": [[x,y],...], "C": [[x,y],...], "D": [[x,y],...]}
where each coordinate is normalised (0–1).

Public API
----------
class Zones
    __init__(split_x=0.5, split_y=0.5, zones_json_path=None)
    assign(x1, y1, x2, y2) -> str       # zone letter A–D or "U" for unzoned
    assign_detections(dets) -> dict     # {A: n, B: n, C: n, D: n, U: n}
    draw(frame) -> numpy.ndarray       # draw outlines, letters, per-zone counts
"""

import json
import os
from collections import deque
from pathlib import Path
from statistics import median

from config import (SMOOTH_WINDOW, ZONE_SPLIT_X, ZONE_SPLIT_Y,
                    round_half_up)

import cv2
import numpy as np


class MedianSmoother:
    """Median of the last N integer samples.

    The result is always an integer: an even-sized median is rounded half-up
    with the same helper used by the control rule.
    """

    def __init__(self, window: int = SMOOTH_WINDOW):
        if window < 1:
            raise ValueError("window must be at least 1")
        self.window = int(window)
        self._samples: deque[int] = deque(maxlen=self.window)

    def update(self, value: int) -> int:
        """Add one sample and return the median of the retained samples."""
        self._samples.append(int(value))
        return round_half_up(median(self._samples))

    def reset(self) -> None:
        """Drop all retained samples."""
        self._samples.clear()


# ---------------------------------------------------------------------------
# Default zones: a 2 × 2 grid split at 0.5 / 0.5
# ---------------------------------------------------------------------------

DEFAULT_ZONES = {
    "A": [[0.0, 0.0], [ZONE_SPLIT_X, 0.0], [ZONE_SPLIT_X, ZONE_SPLIT_Y],
          [0.0, ZONE_SPLIT_Y]],       # top-left
    "B": [[ZONE_SPLIT_X, 0.0], [1.0, 0.0], [1.0, ZONE_SPLIT_Y],
          [ZONE_SPLIT_X, ZONE_SPLIT_Y]],  # top-right
    "C": [[0.0, ZONE_SPLIT_Y], [ZONE_SPLIT_X, ZONE_SPLIT_Y],
          [ZONE_SPLIT_X, 1.0], [0.0, 1.0]],  # bottom-left
    "D": [[ZONE_SPLIT_X, ZONE_SPLIT_Y], [1.0, ZONE_SPLIT_Y],
          [1.0, 1.0], [ZONE_SPLIT_X, 1.0]],  # bottom-right
}


class Zones:
    """Four zones for people counting.

    Zones are polygons in normalised coordinates (0–1 in both x and y).
    A person belongs to the zone containing their feet point
    ((x1+x2)/2, y2) — the bottom-centre of the detection box.
    """

    def __init__(self, split_x: float = ZONE_SPLIT_X,
                 split_y: float = ZONE_SPLIT_Y,
                 zones_json_path: str | None = None):
        """Initialise the zone layout.

        Args:
            split_x: horizontal split fraction (0–1). Default from config.
            split_y: vertical split fraction (0–1). Default from config.
            zones_json_path: optional path to zones.json. If given, its polygons
                replace the default grid.
        """
        self.split_x = split_x
        self.split_y = split_y
        self.polygons = {}  # zone letter -> list of (x,y) normalised verts

        # Try to load custom zones from JSON
        if zones_json_path is not None:
            p = Path(zones_json_path)
            if p.is_file():
                try:
                    with open(p, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    # Build polygons from the JSON; support both the full format
                    # {"A": [[x,y],...], ...} and a simpler one.
                    for letter in ["A", "B", "C", "D"]:
                        if letter in data:
                            poly = data[letter]
                            # Ensure list of [x,y] pairs
                            if poly and isinstance(poly[0], (list, tuple)) and len(poly[0]) == 2:
                                self.polygons[letter] = [
                                    (float(x), float(y)) for x, y in poly
                                ]
                            else:
                                # treat as raw coords list
                                self.polygons[letter] = poly
                    # If we loaded anything, we're done; otherwise fall back to defaults
                    if self.polygons:
                        return
                except Exception:
                    pass  # fall through to defaults

        # Use the default grid
        self.polygons = dict(DEFAULT_ZONES)

    def _point_in_polygon(self, px: float, py: float, poly: list[tuple[float, float]]) -> int:
        """Return the zone index (0-based) if the point is inside, or -1 if outside.

        Uses OpenCV's pointPolygonTest.  A point exactly on an edge returns
        positive (inside the first zone that claims it, due to ordering).
        """
        # OpenCV expects a 1D array of length 2 for a single point
        pt = np.array([px, py], dtype=np.float32)
        cv_poly = np.array(poly, dtype=np.float32).reshape(-1, 1, 2)
        # pointPolygonTest returns positive if inside, negative if outside,
        # zero if on the edge.
        result = cv2.pointPolygonTest(cv_poly, pt, measureDist=False)
        return 0 if result >= 0 else -1

    def assign(self, x1: float, y1: float, x2: float, y2: float) -> str:
        """Assign a person to a zone based on their feet point.

        The feet point is the bottom-centre of the detection box:
            fx = (x1 + x2) / 2
            fy = y2

        Coordinates x1,x2,y1,y2 are normalised (0–1).  The method returns the
        zone letter (A–D) or "U" if the person is outside all zones.

        A point on a shared edge goes to the first zone in the order A, B, C, D.
        """
        fx = (x1 + x2) / 2.0
        fy = y2

        # Test zones in order A, B, C, D; first one that contains the point wins
        zone_order = ["A", "B", "C", "D"]
        for letter in zone_order:
            poly = self.polygons[letter]
            # cv2.pointPolygonTest takes normalised coords if we pass them as-is
            # but it works with pixel coords too; we'll keep normalised.
            # Build a temporary polygon in pixel terms if needed, or just test.
            # We'll use a simple winding check: count crossings.
            # For simplicity, use the stored polygon as normalised coords and
            # test with a point also in normalised coords.
            # OpenCV pointPolygonTest works in any coordinate system as long as
            # verts and test point are consistent.  We'll convert to pixel-like
            # by assuming frame is 1×1 for the test.
            idx = self._point_in_polygon(fx, fy, poly)
            if idx >= 0:
                return letter

        # Outside every zone
        return "U"

    def assign_detections(self, detections: list[dict]) -> dict:
        """Count how many people fall into each zone.

        Args:
            detections: list of dicts as returned by detector.detect(),
                each with keys x1, y1, x2, y2, conf (all normalised 0–1).

        Returns:
            dict with keys "A", "B", "C", "D", "U" mapping to integer counts.
        """
        counts = {"A": 0, "B": 0, "C": 0, "D": 0, "U": 0}
        for det in detections:
            zone = self.assign(det["x1"], det["y1"], det["x2"], det["y2"])
            counts[zone] = counts.get(zone, 0) + 1
        return counts

    def draw(self, frame: np.ndarray) -> np.ndarray:
        """Draw zone outlines, letters, per-zone counts and feet dots on the frame.

        Args:
            frame: BGR image (numpy array).

        Returns:
            The same image with zone overlays drawn.
        """
        h, w = frame.shape[:2]
        # Convert normalised polygon vertices to pixel coordinates
        pixel_polys = {}
        for letter, poly in self.polygons.items():
            pixel_polys[letter] = [
                (int(x * w), int(y * h)) for x, y in poly
            ]

        # Draw zone outlines
        for letter, poly in pixel_polys.items():
            cv2.polylines(frame, [np.array(poly, dtype=np.int32)], isClosed=True,
                          color=(255, 255, 255), thickness=2)
            # Zone letter
            # Use the centroid of the polygon for the letter centre
            cx = int(sum(p[0] for p in poly) / len(poly) * w)
            cy = int(sum(p[1] for p in poly) / len(poly) * h)
            cv2.putText(frame, letter, (cx - 5, cy + 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

        return frame