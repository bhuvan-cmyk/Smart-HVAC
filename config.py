"""Configuration for Smart HVAC - all tunable numbers live here.

All constants are module-level so they can be imported from elsewhere
(e.g. config.VENT_MIN, config.round_half_up).
"""

import math

# ---------------------------------------------------------------------------
# Rounding helper – used by the vent rule to guarantee laptop/ESP32 agreement
# ---------------------------------------------------------------------------

def round_half_up(x: float) -> int:
    """Round x to the nearest integer, halves rounded up.

    Equivalent to ``math.floor(x + 0.5)`` for positive *x*.
    Used instead of Python's ``round()`` which employs banker's rounding.
    """
    return math.floor(x + 0.5)


# ---------------------------------------------------------------------------
# Vision
# ---------------------------------------------------------------------------

SOURCE = "0"                      # webcam index; override with --source http://IP:8080/video etc
MODEL_PATH = "models/yolo11n.pt"  # preferred weights
MODEL_FALLBACK = "yolo11n.pt"     # used only if MODEL_PATH is missing
CONF = 0.25                       # confidence threshold (lower = finds farther people)
IOU = 0.70                        # NMS IoU (higher keeps overlapping people)
IMGSZ = 640                       # 640 = known-good accuracy; 416 misses distant people
                                  # use --imgsz 960 for maximum recall (slower)
DETECT_TILES = 2                  # 1 = full frame, 2 = 2x2 tiles, 3 = 3x3 tiles
TILE_OVERLAP = 0.25               # extra image around each tile's core cell
PERSON_CLASS = 0                  # YOLO class id for person
SMOOTH_WINDOW = 5                 # median window per zone (last N samples)
ZONE_SPLIT_X = 0.5                # default horizontal split for 2x2 grid
ZONE_SPLIT_Y = 0.5                # default vertical split for 2x2 grid


# ---------------------------------------------------------------------------
# Control rule constants
# ---------------------------------------------------------------------------

VENT_MIN = 15            # minimum vent opening % while room is occupied
VENT_MAX = 100           # fully open
FAN_MIN = 20             # fan speed at lowest occupied count
FAN_MAX = 100            # maximum fan speed
FAN_FULL_AT = 10         # total people at which fan reaches 100 %
IDLE_DELAY_S = 5         # seconds at zero occupancy before entering IDLE
SMOOTH_WINDOW_CONTROL = 5  # median window for control loop


# ---------------------------------------------------------------------------
# Smoothing / send timing
# ---------------------------------------------------------------------------

SAMPLE_RATE_HZ = 5          # approximate detections per second
FRAME_FRESH_S = 3           # commands sent only while frame younger than this
SEND_PERIOD_S = 0.2         # send at 5 Hz


# ---------------------------------------------------------------------------
# Camera reader
# ---------------------------------------------------------------------------

CAMERA_FRESH_S = 3.0        # camera is LIVE while its newest frame is younger than this
RECONNECT_DELAY_S = 2.0     # wait between reconnect attempts
CAP_BUFFER_SIZE = 1         # keep only the newest live frame
READER_SLEEP_S = 0.01       # small yield in the reader thread
VIDEO_FPS_FALLBACK = 30.0   # pacing when a video file reports no FPS
CAMERA_OPEN_TIMEOUT_MS = 5000
CAMERA_READ_TIMEOUT_MS = 3000
CAMERA_RESTART_S = 5.0      # restart the capture after this long without a frame


# ---------------------------------------------------------------------------
# Camera orientation
# ---------------------------------------------------------------------------

CAMERA_FLIP = "none"        # none | horizontal | vertical | both
CAMERA_ROTATE = 90          # 0 | 90 | 180 | 270 clockwise (90 fixes the sideways iPhone stream)


# ---------------------------------------------------------------------------
# Phase 1 overlay / console
# ---------------------------------------------------------------------------

CONSOLE_PERIOD_S = 1.0      # print "People: N" once per second
FPS_WINDOW_S = 1.0          # FPS averaging window
OVERLAY_BAR_HEIGHT = 130    # black bar height, pixels
OVERLAY_BIG_BASELINE = 85   # baseline for the huge PEOPLE text
OVERLAY_FONT_SCALE = 2.5    # huge PEOPLE text
OVERLAY_SMALL_FONT_SCALE = 0.7
OVERLAY_THICKNESS = 5
OVERLAY_SMALL_THICKNESS = 2
OVERLAY_MARGIN = 15
BOX_THICKNESS = 2
BOX_LABEL_SCALE = 1.2
BOX_LABEL_THICKNESS = 3
OVERLAY_BG = (0, 0, 0)
OVERLAY_FG = (255, 255, 255)
BOX_COLOR = (0, 255, 0)
PLACEHOLDER_WIDTH = 640
PLACEHOLDER_HEIGHT = 480
WINDOW_NAME = "Smart HVAC"
WINDOW_TOPMOST = True       # keep the demo window above other windows
WINDOW_RESIZABLE = True     # allow drag-resize / maximize
WINDOW_MAX_HEIGHT = 720     # shrink tall portrait frames to fit the screen


# ---------------------------------------------------------------------------
# Fan rounding helper
# ---------------------------------------------------------------------------

def fan_pct(total: int) -> int:
    """Fan % = 20 + 80 × total ÷ 10, capped at 100.

    Integer maths: 20 + 8 * total  (exact since 80 / 10 = 8).
    Returns 0 when the room is empty (IDLE → minimum PWM).
    """
    if total == 0:
        return 0
    return min(100, 20 + 8 * total)


# ---------------------------------------------------------------------------
# Vent rounding helper – half-up with floor(x + 0.5)
# ---------------------------------------------------------------------------

def vent_pct(counts: list[int], maxc: int) -> list[int]:
    """Vent % = 15 + 85 × (zone count ÷ busiest zone's count), round half-up.

    If total == 0:          all vents 0 % (closed).
    If maxc == 0:          all vents 15 % (minimum while occupied).
    Otherwise each vent:
        vent_i = round_half_up(15 + 85 * c_i / maxc)

    The busiest zone always reaches exactly 100 %.
    An empty occupied zone receives exactly 15 %.
    """
    total = sum(counts)
    if total == 0:
        return [0, 0, 0, 0]
    if maxc == 0:
        return [15, 15, 15, 15]
    return [round_half_up(15 + 85 * c / maxc) for c in counts]


# ---------------------------------------------------------------------------
# Count totals (used for fan control)
# ---------------------------------------------------------------------------

def total_count(counts: list[int]) -> int:
    """Total occupancy used for fan control: sum of all zone counts + unzoned."""
    return sum(counts)