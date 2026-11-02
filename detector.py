"""Person detector using Ultralytics YOLO.

For a high/CCTV-style camera, small people in the back of the room are hard to
see after the whole frame is resized to 640 px. The frame is therefore split
into a grid of overlapping tiles; each tile is detected at full model size and
all boxes are mapped back to the full frame. A full-frame pass anchors people
who straddle a tile border, and cut-off fragments that touch a tile border are
discarded. A merge pass then removes the same person seen in two overlapping
tiles while keeping different people who overlap each other.

Public API
----------
class PersonDetector
    __init__(conf, iou, imgsz, person_class, tiles, tile_overlap)
    detect(frame) -> list[dict]
        returns list of dicts {x1,y1,x2,y2,conf} in full-frame pixels
"""

from pathlib import Path

from ultralytics import YOLO
from config import (MODEL_PATH, MODEL_FALLBACK, CONF, IOU, IMGSZ,
                    PERSON_CLASS, DETECT_TILES, TILE_OVERLAP)


def _iou(a: dict, b: dict) -> float:
    """Intersection over union of two {x1,y1,x2,y2} boxes."""
    ix1 = max(a["x1"], b["x1"])
    iy1 = max(a["y1"], b["y1"])
    ix2 = min(a["x2"], b["x2"])
    iy2 = min(a["y2"], b["y2"])
    iw = max(0, ix2 - ix1)
    ih = max(0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    area_a = max(1, (a["x2"] - a["x1"]) * (a["y2"] - a["y1"]))
    area_b = max(1, (b["x2"] - b["x1"]) * (b["y2"] - b["y1"]))
    return inter / (area_a + area_b - inter)


def _contained(a: dict, b: dict) -> bool:
    """True when the smaller box sits inside the larger one.

    A face, hand or torso box inside a full-body box has a low IoU but a high
    intersection-over-smaller-area ratio. This is the case that inflated the
    count when tiling at high resolution.
    """
    area_a = max(1, (a["x2"] - a["x1"]) * (a["y2"] - a["y1"]))
    area_b = max(1, (b["x2"] - b["x1"]) * (b["y2"] - b["y1"]))
    small, large = (a, b) if area_a <= area_b else (b, a)
    small_area = min(area_a, area_b)
    large_area = max(area_a, area_b)

    # Only merge a clearly smaller part (face/hand/limb) into a body box.
    # Two people of comparable size who overlap are different people, and a
    # shorter seated person is a whole person, not a fragment.
    if small_area / large_area > 0.25:
        return False
    small_h = max(1, small["y2"] - small["y1"])
    small_w = max(1, small["x2"] - small["x1"])
    large_h = max(1, large["y2"] - large["y1"])
    fragment = (small_h <= 0.35 * large_h
                or small_h / small_w >= 2.0)
    if not fragment:
        return False

    ix1 = max(small["x1"], large["x1"])
    iy1 = max(small["y1"], large["y1"])
    ix2 = min(small["x2"], large["x2"])
    iy2 = min(small["y2"], large["y2"])
    inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
    if inter / small_area < 0.75:
        return False

    cx = (small["x1"] + small["x2"]) / 2
    cy = (small["y1"] + small["y2"]) / 2
    return (large["x1"] <= cx <= large["x2"]
            and large["y1"] <= cy <= large["y2"])


def _part_of(small: dict, large: dict) -> bool:
    """True when *small* is a body part of the person in *large*.

    A leg, hand or face can be detected as its own person, especially after
    tiling. Such a box is much shorter than a whole person, sits within that
    person's horizontal span, and is usually limb-shaped. A real nearby person
    (similar height, normal body proportions) never matches this rule.
    """
    if _area(small) >= _area(large):
        return False

    hs = max(1, small["y2"] - small["y1"])
    ws = max(1, small["x2"] - small["x1"])
    hl = max(1, large["y2"] - large["y1"])

    if hs > 0.60 * hl:
        return False

    # Must be a clearly tiny fragment (face/hand) or a tall-thin fragment in
    # the lower half of the body (leg). This stops a person standing behind
    # and above the larger box from being absorbed.
    cy = (small["y1"] + small["y2"]) / 2
    large_cy = (large["y1"] + large["y2"]) / 2
    tiny = hs <= 0.35 * hl
    lower_limb = hs / ws >= 2.0 and cy >= large_cy
    if not (tiny or lower_limb):
        return False

    # A leg or arm can sit beside the torso box when the person is striding,
    # so test the body's centre line with a margin instead of strict overlap.
    wl = max(1, large["x2"] - large["x1"])
    cx = (small["x1"] + small["x2"]) / 2
    if not (large["x1"] - 0.25 * wl <= cx <= large["x2"] + 0.25 * wl):
        return False

    # Limbs may hang below a body box that was cut off by a desk. Anyone
    # standing higher in the image (another row) is rejected here.
    return large["y2"] - 0.10 * hl <= small["y2"] <= large["y2"] + 0.35 * hl


def _same_person(a: dict, b: dict) -> bool:
    """True when two boxes are almost certainly the same person.

    Handles the usual tiling duplicates: a body part inside the body box,
    nearly identical boxes, or a clipped box and a full box whose centres sit
    within a small fraction of the body height.
    """
    if _contained(a, b):
        return True
    if _part_of(a, b) or _part_of(b, a):
        return True
    if _iou(a, b) >= 0.55:
        return True

    ha = max(1, a["y2"] - a["y1"])
    hb = max(1, b["y2"] - b["y1"])
    if not (0.5 <= ha / hb <= 2.0):
        return False

    cxa = (a["x1"] + a["x2"]) / 2
    cya = (a["y1"] + a["y2"]) / 2
    cxb = (b["x1"] + b["x2"]) / 2
    cyb = (b["y1"] + b["y2"]) / 2
    scale = min(ha, hb)
    return (abs(cxa - cxb) < 0.12 * scale
            and abs(cya - cyb) < 0.12 * scale)


def _area(box: dict) -> int:
    """Pixel area of a detection box."""
    return max(1, (box["x2"] - box["x1"]) * (box["y2"] - box["y1"]))


def _merge(boxes: list[dict]) -> list[dict]:
    """Group duplicate boxes, keeping the largest full-body box per person."""
    kept: list[dict] = []
    for det in sorted(boxes, key=_area, reverse=True):
        if not any(_same_person(det, other) for other in kept):
            kept.append(det)
    return kept


class PersonDetector:
    """Person detector using Ultralytics YOLO."""

    def __init__(self, conf: float = CONF, iou: float = IOU,
                 imgsz: int = IMGSZ, person_class: int = PERSON_CLASS,
                 tiles: int = DETECT_TILES,
                 tile_overlap: float = TILE_OVERLAP):
        """Load the YOLO model once and store the inference settings."""
        weights = Path(MODEL_PATH)
        self.model = YOLO(str(weights) if weights.is_file() else MODEL_FALLBACK)
        self.conf = float(conf)
        self.iou = float(iou)
        self.imgsz = int(imgsz)
        self.person_class = int(person_class)
        self.tiles = max(1, int(tiles))
        self.tile_overlap = max(0.0, float(tile_overlap))

    def _predict(self, frame, offset_x: int = 0,
                 offset_y: int = 0) -> list[dict]:
        """Run YOLO on one image and return boxes in full-frame coordinates."""
        results = self.model.predict(
            frame,
            classes=[self.person_class],
            conf=self.conf,
            iou=self.iou,
            imgsz=self.imgsz,
            verbose=False,
        )
        if not results:
            return []

        boxes = []
        for box in results[0].boxes:
            x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
            boxes.append({
                "x1": x1 + offset_x,
                "y1": y1 + offset_y,
                "x2": x2 + offset_x,
                "y2": y2 + offset_y,
                "conf": float(box.conf[0].item()),
            })
        return boxes

    def _detect_tiled(self, frame) -> list[dict]:
        """Detect every overlapping tile, then merge duplicate people."""
        height, width = frame.shape[:2]
        cols = rows = self.tiles
        cell_w = width / cols
        cell_h = height / rows
        pad_x = int(cell_w * self.tile_overlap / 2)
        pad_y = int(cell_h * self.tile_overlap / 2)

        found: list[dict] = self._predict(frame)
        for row in range(rows):
            for col in range(cols):
                core_x1 = int(col * cell_w)
                core_x2 = int((col + 1) * cell_w)
                core_y1 = int(row * cell_h)
                core_y2 = int((row + 1) * cell_h)

                tile_x1 = max(0, core_x1 - pad_x)
                tile_x2 = min(width, core_x2 + pad_x)
                tile_y1 = max(0, core_y1 - pad_y)
                tile_y2 = min(height, core_y2 + pad_y)
                tile = frame[tile_y1:tile_y2, tile_x1:tile_x2]
                if tile.size == 0:
                    continue

                for det in self._predict(tile, tile_x1, tile_y1):
                    # A box touching an inner tile border is a cut-off body
                    # part (face, hand, half a torso). The adjacent overlapping
                    # tile sees the whole person; counting this fragment is
                    # what inflated the total.
                    if self._touches_inner_edge(
                        det, tile_x1, tile_x2, tile_y1, tile_y2, width, height
                    ):
                        continue
                    found.append(det)

        return _merge(found)

    @staticmethod
    def _touches_inner_edge(det: dict, tile_x1: int, tile_x2: int,
                            tile_y1: int, tile_y2: int,
                            frame_w: int, frame_h: int,
                            margin: int = 3) -> bool:
        """True when a box is clipped by a tile border that is not a frame edge."""
        if tile_x1 > 0 and det["x1"] <= tile_x1 + margin:
            return True
        if tile_x2 < frame_w and det["x2"] >= tile_x2 - margin:
            return True
        if tile_y1 > 0 and det["y1"] <= tile_y1 + margin:
            return True
        if tile_y2 < frame_h and det["y2"] >= tile_y2 - margin:
            return True
        return False

    def detect(self, frame) -> list[dict]:
        """Detect people in a BGR frame and return full-frame boxes."""
        if self.tiles <= 1:
            return self._predict(frame)
        return self._detect_tiled(frame)
