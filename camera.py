"""Latest-frame camera reader with auto-reconnect and orientation control.

A background thread reads the source continuously. Only the newest frame and
its capture timestamp are kept, so the detector never works through a backlog.
Numeric strings such as "0" are treated as webcam indexes. Local video files
loop at their native frame rate. Live sources reconnect every
config.RECONNECT_DELAY_S seconds after a failure. The caller can request a
reopen without blocking with request_restart().

Orientation is applied when a frame is read: horizontal/vertical flips and
0/90/180/270-degree rotation. This keeps the detector and the displayed image
in the same coordinate system.

Public API
----------
class LatestFrameReader
    __init__(source, flip=config.CAMERA_FLIP, rotate=config.CAMERA_ROTATE)
    start()                       # start the background thread
    read() -> (frame, ts)         # newest frame + timestamp, or (None, None)
    age() -> float                # seconds since the newest successful frame
    ok -> bool                    # True while age < config.CAMERA_FRESH_S
    set_transform(flip, rotate)   # change orientation live
    request_restart()             # ask the reader thread to reopen (non-blocking)
    stop()                        # stop the thread and release the capture
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Union

import cv2
import numpy as np

import config

logger = logging.getLogger(__name__)

Source = Union[int, str]
FLIP_MODES = ("none", "horizontal", "vertical", "both")
ROTATIONS = (0, 90, 180, 270)


def _normalise_source(source: Source) -> Source:
    """Turn a numeric string such as "0" into a webcam index."""
    if isinstance(source, int):
        return source
    text = str(source).strip()
    if text.isdigit():
        return int(text)
    return text


def apply_transform(frame: np.ndarray, flip: str, rotate: int) -> np.ndarray:
    """Flip and rotate a frame according to the configured orientation."""
    if flip == "horizontal":
        frame = cv2.flip(frame, 1)
    elif flip == "vertical":
        frame = cv2.flip(frame, 0)
    elif flip == "both":
        frame = cv2.flip(frame, -1)

    if rotate == 90:
        frame = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
    elif rotate == 180:
        frame = cv2.rotate(frame, cv2.ROTATE_180)
    elif rotate == 270:
        frame = cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
    return frame


class LatestFrameReader:
    """Read a camera/stream/file and keep only the newest frame."""

    def __init__(self, source: Source, flip: str = config.CAMERA_FLIP,
                 rotate: int = config.CAMERA_ROTATE):
        if flip not in FLIP_MODES:
            raise ValueError(f"flip must be one of {FLIP_MODES}")
        if rotate not in ROTATIONS:
            raise ValueError(f"rotate must be one of {ROTATIONS}")

        self.source = _normalise_source(source)
        text = str(self.source)
        self._is_url = text.startswith(("http://", "https://", "rtsp://"))
        self._is_file = not self._is_url and Path(text).is_file()

        self._cap: cv2.VideoCapture | None = None
        self._frame: np.ndarray | None = None
        self._frame_ts: float | None = None
        self._flip = flip
        self._rotate = int(rotate)
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._restart_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._frame_period = 0.0

    def start(self) -> None:
        """Start the reader thread. Safe to call more than once."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._restart_event.clear()
        self._thread = threading.Thread(
            target=self._reader_loop, name="camera-reader", daemon=True
        )
        self._thread.start()

    def _open(self) -> None:
        if self._is_url:
            # Pass timeouts at open time so a dead phone does not block forever.
            try:
                cap = cv2.VideoCapture(
                    self.source,
                    cv2.CAP_FFMPEG,
                    [
                        cv2.CAP_PROP_OPEN_TIMEOUT_MSEC,
                        config.CAMERA_OPEN_TIMEOUT_MS,
                        cv2.CAP_PROP_READ_TIMEOUT_MSEC,
                        config.CAMERA_READ_TIMEOUT_MS,
                    ],
                )
            except (TypeError, cv2.error):
                cap = cv2.VideoCapture(self.source, cv2.CAP_FFMPEG)
            if not cap.isOpened():
                # Some builds do not expose the FFMPEG backend.
                cap.release()
                cap = cv2.VideoCapture(self.source)
        else:
            cap = cv2.VideoCapture(self.source)

        if not cap.isOpened():
            cap.release()
            raise RuntimeError(f"cannot open source {self.source!r}")

        # Keep only the newest live frame. File playback is paced separately.
        if not self._is_file:
            cap.set(cv2.CAP_PROP_BUFFERSIZE, config.CAP_BUFFER_SIZE)

        # Also set the properties after opening for backends that need it.
        if self._is_url:
            if hasattr(cv2, "CAP_PROP_OPEN_TIMEOUT_MSEC"):
                cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC,
                        config.CAMERA_OPEN_TIMEOUT_MS)
            if hasattr(cv2, "CAP_PROP_READ_TIMEOUT_MSEC"):
                cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC,
                        config.CAMERA_READ_TIMEOUT_MS)
            if not cap.isOpened():
                cap.release()
                raise RuntimeError(
                    f"stream did not open within "
                    f"{config.CAMERA_OPEN_TIMEOUT_MS} ms: {self.source!r}"
                )

        self._cap = cap
        if self._is_file:
            fps = cap.get(cv2.CAP_PROP_FPS)
            self._frame_period = (
                1.0 / fps if fps and fps > 0
                else 1.0 / config.VIDEO_FPS_FALLBACK
            )
        logger.info("Opened camera source %r", self.source)

    def _release_cap(self) -> None:
        cap = self._cap
        self._cap = None
        if cap is not None:
            cap.release()

    def _reader_loop(self) -> None:
        while not self._stop_event.is_set():
            if self._restart_event.is_set():
                self._restart_event.clear()
                logger.info("Restart requested; reopening source")
                self._release_cap()

            if self._cap is None:
                try:
                    self._open()
                except Exception as exc:
                    logger.warning(
                        "Camera open failed: %s (retrying in %.1fs)",
                        exc, config.RECONNECT_DELAY_S,
                    )
                    self._stop_event.wait(config.RECONNECT_DELAY_S)
                    continue

            ok, frame = self._cap.read()
            if not ok or frame is None:
                if self._is_file and self._cap is not None:
                    # End of a video file: rewind and continue.
                    self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    self._stop_event.wait(
                        max(self._frame_period, config.READER_SLEEP_S)
                    )
                else:
                    logger.warning("Camera read failed; reconnecting")
                    self._release_cap()
                    self._stop_event.wait(config.RECONNECT_DELAY_S)
                continue

            with self._lock:
                self._frame = frame
                self._frame_ts = time.time()

            if self._is_file:
                count = self._cap.get(cv2.CAP_PROP_FRAME_COUNT)
                pos = self._cap.get(cv2.CAP_PROP_POS_FRAMES)
                if count > 1 and pos >= count - 1:
                    self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                self._stop_event.wait(
                    max(self._frame_period, config.READER_SLEEP_S)
                )
            else:
                self._stop_event.wait(config.READER_SLEEP_S)

    def read(self) -> tuple[np.ndarray | None, float | None]:
        """Return an oriented copy of the newest frame and its timestamp."""
        with self._lock:
            if self._frame is None:
                return None, None
            frame = self._frame.copy()
            ts = self._frame_ts
            flip = self._flip
            rotate = self._rotate
        return apply_transform(frame, flip, rotate), ts

    def set_transform(self, flip: str, rotate: int) -> None:
        """Change the orientation applied to subsequent reads."""
        if flip not in FLIP_MODES:
            raise ValueError(f"flip must be one of {FLIP_MODES}")
        if rotate not in ROTATIONS:
            raise ValueError(f"rotate must be one of {ROTATIONS}")
        with self._lock:
            self._flip = flip
            self._rotate = int(rotate)

    def age(self) -> float:
        """Seconds since the newest successful frame (1e9 before the first)."""
        with self._lock:
            if self._frame_ts is None:
                return 1e9
            return time.time() - self._frame_ts

    @property
    def ok(self) -> bool:
        """True while the newest frame is younger than CAMERA_FRESH_S."""
        return self.age() < config.CAMERA_FRESH_S

    def request_restart(self) -> None:
        """Ask the reader thread to reopen the source without blocking."""
        self._restart_event.set()

    def stop(self) -> None:
        """Stop the reader thread and release the capture."""
        self._stop_event.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=5.0)
            if thread.is_alive():
                # A backend that ignores the read timeout may still be blocked.
                logger.warning("Camera reader did not stop; releasing capture")
                self._release_cap()
                thread.join(timeout=2.0)
            self._thread = None
        self._release_cap()
