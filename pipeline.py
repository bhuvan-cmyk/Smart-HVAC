"""Pipeline that ties together detector, smoother, control, and state.

The Pipeline class holds the YOLO detector, per-zone MedianSmoother instances,
the latest annotated JPEG (quality 70), and the latest control state dict.
It is protected by a lock for thread safety.

Public API
----------
class Pipeline
    __init__()   # initialise detector, smoothers, state
    process(frame, ts) -> state   # main processing loop
    state_dict() -> dict   # latest state
    annotated_jpeg() -> bytes   # latest annotated JPEG (quality 70)
"""

import threading
import time
import numpy as np
import cv2
from datetime import datetime

from config import CONF, IOU, IMGSZ, PERSON_CLASS, SMOOTH_WINDOW_CONTROL
from detector import PersonDetector
from zones import Zones
from control import vent_percentages, fan_percent, Controller


class Pipeline:
    """Tie together detection, zone assignment, smoothing, and control.

    The main processing loop:
      1. Detect people in the frame.
      2. Assign each person to a zone (feet point).
      3. Update per-zone median smoothers.
      4. Apply the control rule.
      5. Draw annotations on a copy of the frame.
      6. Update the latest state dict and annotated JPEG.

    Thread safety: all public methods should be called from the main thread,
    or the caller must hold the internal lock.
    """

    def __init__(self):
        """Initialise the pipeline: detector, zones, controller, and state."""
        self._lock = threading.Lock()
        self._detector = PersonDetector()
        self._zones = Zones()
        self._controller = Controller()

        # Per-zone median smoothers: last N samples (N = SMOOTH_WINDOW_CONTROL)
        self._zone_counts = {"A": [], "B": [], "C": [], "D": []}
        self._smoother_window = max(1, SMOOTH_WINDOW_CONTROL)

        # Latest state
        self._state = {
            "total": 0,
            "raw_total": 0,
            "zone_counts": {"A": 0, "B": 0, "C": 0, "D": 0},
            "vents": [0, 0, 0, 0],
            "fan": 0,
            "mode": "IDLE",
            "fps": 0.0,
            "latency_ms": 0,
            "timestamp": time.time(),
        }

        # Latest annotated JPEG (quality 70 for bandwidth)
        self._annotated_jpeg = None
        self._jpeg_quality = 70

    def process(self, frame, ts):
        """Process a single frame and update internal state.

        The main pipeline: detect → assign zones → smooth → control → draw.

        Args:
            frame: BGR numpy array from the camera.
            ts: timestamp of the frame (seconds, time.time()).

        Returns:
            dict with the latest state (same shape as state_dict()).
        """
        with self._lock:
            start_t = time.time()

            # 1. Detect people
            detections = self._detector.detect(frame)

            # 2. Assign each detection to a zone.  The detector returns pixel
            # boxes, while Zones.assign() expects normalised 0-1 coordinates.
            h, w = frame.shape[:2]
            norm_detections = [
                {
                    "x1": det["x1"] / w,
                    "y1": det["y1"] / h,
                    "x2": det["x2"] / w,
                    "y2": det["y2"] / h,
                    "conf": det["conf"],
                }
                for det in detections
            ]
            zone_counts = self._zones.assign_detections(norm_detections)

            # 3. Update per-zone smoothers (median of last N values)
            for zone in ["A", "B", "C", "D"]:
                self._zone_counts[zone].append(zone_counts[zone])
                # Keep only the last N samples
                if len(self._zone_counts[zone]) > self._smoother_window:
                    self._zone_counts[zone].pop(0)

                # Compute the median count for this zone
                # If we have fewer than window samples, just use what we have
                samples = self._zone_counts[zone]
                if samples:
                    sorted_sorted = sorted(samples)
                    n = len(sorted_sorted)
                    if n % 2 == 1:
                        median = sorted_sorted[n // 2]
                    else:
                        median = (sorted_sorted[n // 2 - 1] + sorted_sorted[n // 2]) / 2
                    # Round to integer (people count)
                    zone_counts[zone] = int(median)
                else:
                    zone_counts[zone] = 0

            # Clamp counts to 0–99 before sending to ESP32
            clamped = {z: max(0, min(99, zone_counts[z])) for z in ["A", "B", "C", "D"]}

            # 4. Apply the control rule
            counts = [clamped["A"], clamped["B"], clamped["C"], clamped["D"]]
            maxc = max(counts) if counts else 0
            now = time.time()

            ctrl = self._controller.update(counts, now)
            vents = ctrl["vents"]
            fan = ctrl["fan"]
            mode = ctrl["mode"]

            # 5. Compute total and raw total
            raw_total = sum(zone_counts.values())
            total = raw_total  # no unzoned people in the basic pipeline

            # 6. Compute fan percentage using the helper from config
            fan_pct = fan_percent(total)

            # 7. Update state dict
            self._state = {
                "total": total,
                "raw_total": raw_total,
                "zone_counts": clamped,
                "vents": vents,
                "fan": fan_pct,
                "mode": mode,
                "fps": round(1.0 / (time.time() - start_t + 1e-6), 2),
                "latency_ms": int((time.time() - ts) * 1000) if ts else 0,
                "timestamp": now,
            }

            # 8. Draw annotations on a copy of the frame
            annotated = frame.copy()
            # Draw person boxes and feet points
            for det in detections:
                x1, y1, x2, y2 = det["x1"], det["y1"], det["x2"], det["y2"]
                # Convert normalised to pixel if needed; assuming frame coords already
                cv2.rectangle(annotated, (x1, y1), (x2, y2), color=(0, 255, 0), thickness=2)
                # Feet point
                fx = (x1 + x2) / 2
                fy = y2
                cv2.circle(annotated, (int(fx), int(fy)), 4, (0, 0, 255), -1)

            # Draw zone outlines and counts (using zones.draw)
            annotated = self._zones.draw(annotated)

            # Draw side panel: total count and vents/fan
            cv2.putText(annotated, f"TOTAL: {total}", (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
            cv2.putText(annotated, f"MODE: {mode}", (10, 60),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            # Vent bars
            for i, v in enumerate(vents):
                bar_w = 20
                bar_h = int(v * 2)  # scale visible height
                # Draw vertical bar
                cx = 10 + i * 55 + 25
                cy_start = h - 10 if (h := annotated.shape[0]) else 200
                cv2.rectangle(annotated, (cx, cy_start - bar_h), (cx + bar_w, cy_start), (255, 255, 0), -1)
                cv2.putText(annotated, str(v), (cx, cy_start + 20),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

            # Encode as JPEG quality 70
            ok, buf = cv2.imencode(".jpg", annotated, [int(cv2.IMWRITE_JPEG_QUALITY), self._jpeg_quality])
            if ok:
                self._annotated_jpeg = buf.tobytes()

            # Return the current state
            return dict(self._state)

    def state_dict(self) -> dict:
        """Return the latest state dictionary.

        Returns:
            dict with keys: total, raw_total, zone_counts, vents, fan, mode, fps,
            latency_ms, timestamp.
        """
        with self._lock:
            return dict(self._state)

    def annotated_jpeg(self) -> bytes:
        """Return the latest annotated JPEG frame (quality 70).

        Returns:
            bytes JPEG image, or None if no frame has been processed yet.
        """
        with self._lock:
            return self._annotated_jpeg