"""Phase 1 entry point: count people from a camera, phone stream, video, or image.

Examples
--------
python main.py --source 0 --window
python main.py --source http://PHONE_IP:8080/video --window
python main.py --source tests/bus.jpg
python main.py --source clip.mp4 --window
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import cv2
import numpy as np

import config
from camera import FLIP_MODES, ROTATIONS, LatestFrameReader
from detector import PersonDetector
from zones import MedianSmoother

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def build_parser() -> argparse.ArgumentParser:
    """Return the command-line parser."""
    parser = argparse.ArgumentParser(
        description="Smart HVAC - phase 1 people counting"
    )
    parser.add_argument(
        "--source",
        default=config.SOURCE,
        help=(
            "Camera source: webcam index ('0'), HTTP(S)/RTSP URL, video file, "
            "or a still image (processed once)"
        ),
    )
    parser.add_argument(
        "--window",
        action="store_true",
        help="Show the annotated OpenCV window; press q to quit",
    )
    parser.add_argument(
        "--conf",
        type=float,
        default=config.CONF,
        help="YOLO confidence threshold (default: %(default)s)",
    )
    parser.add_argument(
        "--imgsz",
        type=int,
        default=config.IMGSZ,
        help="YOLO inference size (default: %(default)s)",
    )
    parser.add_argument(
        "--tiles",
        type=int,
        choices=(1, 2, 3),
        default=config.DETECT_TILES,
        help="Split the frame into N x N tiles to find small/far people "
             "(default: %(default)s)",
    )
    parser.add_argument(
        "--flip",
        choices=("none", "horizontal", "vertical", "both"),
        default=config.CAMERA_FLIP,
        help="Flip the camera image (default: %(default)s)",
    )
    parser.add_argument(
        "--rotate",
        type=int,
        choices=(0, 90, 180, 270),
        default=config.CAMERA_ROTATE,
        help="Rotate the camera image clockwise (default: %(default)s)",
    )
    return parser


def is_image_source(source: str) -> bool:
    """True when the source is an existing local image file."""
    path = Path(source)
    return path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES


def fit_for_display(frame: np.ndarray) -> np.ndarray:
    """Shrink tall portrait frames so the window fits on screen."""
    height, width = frame.shape[:2]
    if height <= config.WINDOW_MAX_HEIGHT:
        return frame
    scale = config.WINDOW_MAX_HEIGHT / height
    return cv2.resize(
        frame, (int(width * scale), config.WINDOW_MAX_HEIGHT),
        interpolation=cv2.INTER_AREA,
    )


def draw_annotations(frame: np.ndarray, detections: list[dict],
                     smoothed: int | None, raw: int, fps: float,
                     camera_ok: bool) -> np.ndarray:
    """Draw numbered person boxes, the black bar, count and status line.

    ``smoothed=None`` means no frame has been processed yet, so the count is
    shown as "--" rather than a false zero.
    """
    for index, det in enumerate(detections, start=1):
        x1, y1 = int(det["x1"]), int(det["y1"])
        x2, y2 = int(det["x2"]), int(det["y2"])
        cv2.rectangle(
            frame, (x1, y1), (x2, y2),
            config.BOX_COLOR, config.BOX_THICKNESS,
        )
        cv2.putText(
            frame,
            f"#{index}",
            (x1, max(y1 - 8, 18)),
            cv2.FONT_HERSHEY_SIMPLEX,
            config.BOX_LABEL_SCALE,
            config.BOX_COLOR,
            config.BOX_LABEL_THICKNESS,
            cv2.LINE_AA,
        )

    height, width = frame.shape[:2]
    bar_height = min(config.OVERLAY_BAR_HEIGHT, height)
    cv2.rectangle(
        frame, (0, 0), (width, bar_height), config.OVERLAY_BG, -1
    )

    big_y = min(config.OVERLAY_BIG_BASELINE, bar_height - config.OVERLAY_MARGIN)
    small_y = bar_height - config.OVERLAY_MARGIN
    cv2.putText(
        frame,
        f"PEOPLE: {'--' if smoothed is None else smoothed}",
        (config.OVERLAY_MARGIN, big_y),
        cv2.FONT_HERSHEY_SIMPLEX,
        config.OVERLAY_FONT_SCALE,
        config.OVERLAY_FG,
        config.OVERLAY_THICKNESS,
        cv2.LINE_AA,
    )
    status = "LIVE" if camera_ok else "LOST"
    cv2.putText(
        frame,
        f"raw {raw} | FPS {fps:.1f} | camera {status}",
        (config.OVERLAY_MARGIN, small_y),
        cv2.FONT_HERSHEY_SIMPLEX,
        config.OVERLAY_SMALL_FONT_SCALE,
        config.OVERLAY_FG,
        config.OVERLAY_SMALL_THICKNESS,
        cv2.LINE_AA,
    )
    return frame


def run_image(source: str, detector: PersonDetector,
              smoother: MedianSmoother) -> int:
    """Process one image, print the count, save out_<name>.jpg, and exit."""
    path = Path(source)
    frame = cv2.imread(str(path))
    if frame is None:
        print(f"ERROR: cannot read image: {source}", file=sys.stderr)
        return 1

    detections = detector.detect(frame)
    raw = len(detections)
    smoothed = smoother.update(raw)
    draw_annotations(frame, detections, smoothed, raw, 0.0, True)

    out_path = Path.cwd() / f"out_{path.stem}.jpg"
    if not cv2.imwrite(str(out_path), frame):
        print(f"ERROR: cannot write {out_path}", file=sys.stderr)
        return 1

    print(f"People: {smoothed}")
    print(f"Saved {out_path.name}")
    return 0


def handle_window_key(cam: LatestFrameReader, flip_mode: str,
                      rotation: int) -> tuple[bool, str, int]:
    """Handle q/f/r in the OpenCV window.

    Returns (keep_running, flip_mode, rotation).
    """
    key = cv2.waitKey(1) & 0xFF
    if key == ord("q"):
        return False, flip_mode, rotation
    if key == ord("f"):
        flip_mode = FLIP_MODES[
            (FLIP_MODES.index(flip_mode) + 1) % len(FLIP_MODES)
        ]
        cam.set_transform(flip_mode, rotation)
        print(f"Flip: {flip_mode} | Rotate: {rotation}", flush=True)
    elif key == ord("r"):
        rotation = ROTATIONS[
            (ROTATIONS.index(rotation) + 1) % len(ROTATIONS)
        ]
        cam.set_transform(flip_mode, rotation)
        print(f"Flip: {flip_mode} | Rotate: {rotation}", flush=True)
    return True, flip_mode, rotation


def run_stream(source: str, args: argparse.Namespace) -> int:
    """Read the newest frame in a loop, detect people, and show the count."""
    detector = PersonDetector(conf=args.conf, imgsz=args.imgsz,
                              tiles=args.tiles)
    smoother = MedianSmoother(config.SMOOTH_WINDOW)
    cam = LatestFrameReader(
        source, flip=args.flip, rotate=args.rotate
    )
    cam.start()

    window_ok = bool(args.window)
    if window_ok:
        try:
            cv2.namedWindow(
                config.WINDOW_NAME,
                cv2.WINDOW_NORMAL if config.WINDOW_RESIZABLE
                else cv2.WINDOW_AUTOSIZE,
            )
            if config.WINDOW_TOPMOST:
                cv2.setWindowProperty(
                    config.WINDOW_NAME, cv2.WND_PROP_TOPMOST, 1
                )
        except cv2.error as exc:
            print(f"Window disabled: {exc}", file=sys.stderr)
            window_ok = False
    flip_mode = args.flip
    rotation = int(args.rotate)
    fps = 0.0
    fps_frames = 0
    fps_start = time.time()
    last_print = 0.0
    last_restart = time.time()
    smoothed: int | None = None
    raw = 0
    camera_ok = False
    announced_down = False

    try:
        while True:
            frame, _ts = cam.read()
            now = time.time()

            if frame is None or not cam.ok:
                fps = 0.0
                fps_frames = 0
                fps_start = now
                if not announced_down:
                    print("Camera: waiting for video...", flush=True)
                    announced_down = True
                camera_ok = False
                smoothed = None
                smoother.reset()

                if now - last_restart >= config.CAMERA_RESTART_S:
                    cam.request_restart()
                    last_restart = now

                if window_ok:
                    placeholder = np.zeros(
                        (config.PLACEHOLDER_HEIGHT, config.PLACEHOLDER_WIDTH, 3),
                        dtype=np.uint8,
                    )
                    draw_annotations(
                        placeholder, [], None, 0, 0.0, False
                    )
                    cv2.putText(
                        placeholder,
                        "Waiting for camera...",
                        (config.OVERLAY_MARGIN, config.PLACEHOLDER_HEIGHT // 2),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        config.OVERLAY_SMALL_FONT_SCALE,
                        config.OVERLAY_FG,
                        config.OVERLAY_SMALL_THICKNESS,
                        cv2.LINE_AA,
                    )
                    cv2.imshow(config.WINDOW_NAME, placeholder)
                    keep_running, flip_mode, rotation = handle_window_key(
                        cam, flip_mode, rotation
                    )
                    if not keep_running:
                        break
                else:
                    time.sleep(config.READER_SLEEP_S)
                continue

            last_restart = now
            if not camera_ok:
                print("Camera: connected", flush=True)
                camera_ok = True
                announced_down = False
                smoother.reset()
            detections = detector.detect(frame)
            raw = len(detections)
            smoothed = smoother.update(raw)

            fps_frames += 1
            elapsed = now - fps_start
            if elapsed >= config.FPS_WINDOW_S:
                fps = fps_frames / max(elapsed, 1e-6)
                fps_frames = 0
                fps_start = now

            draw_annotations(
                frame, detections, smoothed, raw, fps, cam.ok
            )

            if window_ok:
                try:
                    cv2.imshow(
                        config.WINDOW_NAME, fit_for_display(frame)
                    )
                except cv2.error as exc:
                    print(f"Window disabled: {exc}", file=sys.stderr)
                    window_ok = False
                else:
                    keep_running, flip_mode, rotation = handle_window_key(
                        cam, flip_mode, rotation
                    )
                    if not keep_running:
                        break

            if now - last_print >= config.CONSOLE_PERIOD_S:
                print(f"People: {smoothed}", flush=True)
                last_print = now

    finally:
        cam.stop()
        cv2.destroyAllWindows()

    return 0


def main() -> int:
    """Parse arguments and run image or stream mode."""
    parser = build_parser()
    args = parser.parse_args()

    if not 0.0 < args.conf <= 1.0:
        parser.error("--conf must be greater than 0 and at most 1")
    if args.imgsz < 32:
        parser.error("--imgsz must be at least 32")

    if is_image_source(args.source):
        detector = PersonDetector(conf=args.conf, imgsz=args.imgsz, tiles=1)
        smoother = MedianSmoother(config.SMOOTH_WINDOW)
        return run_image(args.source, detector, smoother)

    print(
        f"Source: {args.source} | conf: {args.conf} | imgsz: {args.imgsz} | "
        f"tiles: {args.tiles} | flip: {args.flip} | rotate: {args.rotate}"
    )
    print(
        "Phone stream: python main.py --source "
        "http://PHONE_IP:8080/video --window"
    )
    print("Keys: q quit | f cycle flip | r rotate 90 degrees")
    try:
        return run_stream(args.source, args)
    except KeyboardInterrupt:
        print("\nStopped.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
