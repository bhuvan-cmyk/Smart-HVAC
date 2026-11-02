# Smart HVAC - Camera-Based Zone Occupancy

A low-cost, occupancy-aware HVAC prototype. A phone camera or IP camera feeds a
laptop; YOLO11n detects people; each person is assigned to one of four room
zones; a median filter stabilises the counts; and a small control rule turns
zone counts into vent openings and fan speed.

The project separates the vision workload from the real-time actuator path. The
laptop does detection and control. The ESP32 is intended to convert percentages
into servo/PWM outputs, apply slew limits, and own the 10 s failsafe.

**Status:** the camera people-counting path (`main.py`) and the pure control
rules are implemented and tested. The browser dashboard and ESP32 firmware are
not part of the verified demo in this snapshot; see [Scope](#scope) below.

## Quick start

### 1. Create an environment

Windows PowerShell:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Linux / macOS:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 2. Run the still-image test

```powershell
python main.py --source tests\bus.jpg
```

Expected output:

```text
People: 4
Saved out_bus.jpg
```

`out_bus.jpg` is generated locally and is ignored by Git.

### 3. Run a live source

```powershell
# Webcam
python main.py --source 0 --window

# Phone stream (DroidCam or IP Webcam)
python main.py --source "http://PHONE_IP:4747/video" --window

# Video file
python main.py --source clip.mp4 --window
```

Window keys: `q` quit, `f` cycle flip, `r` rotate 90 degrees.

The first run downloads `yolo11n.pt` from Ultralytics if
`models/yolo11n.pt` is absent. For offline use, see
[`models/README.md`](models/README.md).

## Scope

| Path | Status in this snapshot | Purpose |
|---|---|---|
| `main.py` | Verified | CLI: image or stream in, annotated frame and `People: N` out |
| `camera.py` | Verified | Newest-frame reader with reconnect and orientation control |
| `detector.py` | Verified | YOLO11n, 2x2 tiled inference, edge rejection, duplicate merge |
| `config.py` | Verified | All tunable vision, camera, and control constants |
| `zones.py` | Verified | Feet-point zone assignment and median smoother |
| `control.py` | Verified by unit tests | Pure vent/fan rules and IDLE state machine |
| `serial_link.py` | Implemented; hardware path not verified | USB serial link to the ESP32, with dummy fallback |
| `pipeline.py` | Prototype | Glue for the dashboard path; not used by `main.py` |
| `server.py` | Prototype | Flask dashboard/phone-camera source; not launched by `main.py` |
| `tests/` | Verified | 22 unit tests, no model or hardware required |
| `esp32/` | Design only | Firmware sketch is not included; see `esp32/README.md` |
| `smart-hvac-final-report.md` | Design report | Authoritative system specification |
| `DEMO_RUNBOOK.md` | Verified | Step-by-step demo procedure |
| `submission/` | Local only | Submission bundle; ignored by Git |

The report is the design specification. Where this README and the report differ
on **status**, this README reflects what is actually runnable in this snapshot.

## How it works

1. `camera.py` reads the newest frame in a background thread, so the detector
   never works through a backlog.
2. `detector.py` runs YOLO11n on the full frame and on a 2x2 grid of
   overlapping tiles. Tiling finds small or distant people that a single 640 px
   resize would miss.
3. Tile boxes are mapped back to full-frame pixel coordinates. Boxes that touch
   an inner tile border are treated as cut-off fragments and discarded.
4. A merge pass keeps the largest full-body box per person. It removes
   duplicates, contained fragments (face/hand), and limb-shaped false
   positives, while keeping two people who overlap each other.
5. `zones.py` assigns each person to the zone containing the bottom-centre of
   their box (the "feet point") and smooths each zone count with a median
   filter.
6. `control.py` computes each vent opening from the zone's share of the
   busiest zone, and fan speed from total occupancy. At confirmed zero
   occupancy the system enters IDLE.

## Repository layout

```text
smart-hvac/
├─ main.py                     # camera/image demo entry point
├─ camera.py                   # newest-frame reader
├─ detector.py                 # YOLO11n tiled detector
├─ config.py                   # all tunable values
├─ zones.py                    # zone polygons + median smoother
├─ control.py                  # pure vent/fan rules
├─ serial_link.py              # laptop -> ESP32 serial link
├─ pipeline.py                 # dashboard pipeline (prototype)
├─ server.py                   # Flask dashboard (prototype)
├─ requirements.txt            # normal dependencies
├─ requirements-lock.txt       # exact tested versions
├─ tests/
│  ├─ test_control.py
│  ├─ test_zones.py
│  └─ bus.jpg                  # Ultralytics sample image
├─ models/
│  └─ README.md                # weights are downloaded, not committed
├─ esp32/
│  └─ README.md                # firmware status + serial contract
├─ .github/workflows/tests.yml # CI: unit tests only
├─ README.md
├─ REFERENCES.md               # research, libraries, and code provenance
├─ THIRD_PARTY_NOTICES.md      # dependency licences and asset credits
├─ LICENSE                     # AGPL-3.0
├─ DEMO_RUNBOOK.md
└─ smart-hvac-final-report.md
```

## Tests

The tests do not need model weights, a camera, or an ESP32:

```powershell
python -m pytest -q
```

Expected:

```text
22 passed
```

CI runs the same tests with `numpy`, `opencv-python-headless`, and `pytest`.
The full `ultralytics`/PyTorch stack is not installed in CI because the tests
cover the pure geometry and control logic only.

## Model weights and sample image

- `models/yolo11n.pt` is **not committed**. It is a 5.6 MB binary; the
  Ultralytics package downloads it on first use, or you can place it in
  `models/` for offline work.
- `tests/bus.jpg` is the Ultralytics sample image, used with attribution. See
  [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).
- `yolo11s.pt`, `models/yolo11n_openvino_model/`, and `out_*.jpg` are local
  artifacts and are ignored.

## Privacy and safe use

- Live frames are processed in memory. The stream demo does not write video to
  disk.
- The project counts bounding boxes; it does not perform face recognition or
  identify individuals.
- The dashboard, if used, is a local-network prototype with no authentication.
  Do not expose it to the public internet.
- Tell people in the room that a camera is being used for occupancy counting,
  even when images are not stored.
- The ESP32 failsafe is a safety feature, not a certified safety instrument.
  Do not use this prototype for life-safety or commercial HVAC control without
  independent review and the appropriate licences.

## Licence

This project is released under the **GNU Affero General Public License v3.0
(AGPL-3.0)** because it uses Ultralytics YOLO11, which is AGPL-3.0. See
[`LICENSE`](LICENSE) and [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).

If you modify this project and make it available as a network service, the
AGPL requires you to offer the corresponding source to users of that service.
A commercial Ultralytics licence is required for a closed-source product.

## References and provenance

The project uses published algorithms and documented library APIs. The exact
mapping from each source file/function to its source is in
[`REFERENCES.md`](REFERENCES.md). A print-friendly version of the camera module
source, including the same reference section, is produced locally as
`submission/SMART_HVAC_CAMERA_DETECTION.pdf` (not tracked by Git).

Key references:

- Ultralytics YOLO11 documentation and software
- Redmon et al., *You Only Look Once* (CVPR 2016)
- Akyon et al., *Slicing Aided Hyper Inference* (ICIP 2022)
- Neubeck & Van Gool, *Efficient Non-Maximum Suppression* (ICPR 2006)
- Jaccard (1901), Tukey (1977), and Astola & Kuosmanen (1997) for the
  intersection-over-union and median-filter background
- OpenCV, NumPy, Flask, PySerial, cryptography, and pytest documentation

## What is intentionally not tracked

The following are local-only and covered by `.gitignore`:

- `.venv/`, `__pycache__/`, `.pytest_cache/`, coverage and cache files
- model weights and generated OpenVINO/ONNX exports
- `logs/`, `zones.json`, and `out_*.jpg`
- the `submission/` bundle and generated ZIP archives
- presentation files (`*.ppt`, `*.pptx`, internal PPT guides)
- PDFs of the presentation, local videos, secrets, certificates, and editor
  settings

This keeps the public repository small and avoids publishing personal,
institutional, or machine-specific material.
