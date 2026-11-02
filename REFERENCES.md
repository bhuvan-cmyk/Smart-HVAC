# References and code provenance

This document records the research, algorithms, libraries, and assets used by
the Smart HVAC project, and maps each source file/function to its origin. It is
the authoritative reference list for the repository and for the camera-module
PDF.

Two kinds of attribution are used:

- **Original project code** - written for this project. No upstream source
  file was copied.
- **Library / published idea** - the code calls a documented library API or
  implements a published algorithm or concept. The implementation is still
  project code unless stated otherwise.

No SAHI package is imported, no Ultralytics source file is vendored, and no
external source file is copied into this repository.

---

## 1. Reference list

### Vision and algorithms

[1] Ultralytics. *YOLO11 documentation.*
<https://docs.ultralytics.com/models/yolo11/> (accessed 2 November 2026).

[2] Espressif Systems. *ESP32 Series Datasheet.*
<https://www.espressif.com/en/products/socs/esp32> (accessed 2 November 2026).

[3] Espressif Systems. *Arduino-ESP32 documentation.*
<https://docs.espressif.com/projects/arduino-esp32/en/latest/> (accessed
2 November 2026).

[4] Free Software Foundation. *GNU Affero General Public License, version 3.*
<https://www.gnu.org/licenses/agpl-3.0.html> (accessed 2 November 2026).

[5] OpenCV. *Image Processing - pointPolygonTest.*
<https://docs.opencv.org/4.x/d6/d6e/group__imgproc__shape.html> (accessed
2 November 2026).

[6] Jocher, G., & Qiu, J. (2024). *Ultralytics YOLO11* (Version 11.0.0)
[Computer software]. <https://github.com/ultralytics/ultralytics>.
AGPL-3.0. The project was tested with the `ultralytics` Python package
version 8.4.190.

[7] Redmon, J., Divvala, S., Girshick, R., & Farhadi, A. (2016). You Only Look
Once: Unified, Real-Time Object Detection. *Proceedings of the IEEE Conference
on Computer Vision and Pattern Recognition (CVPR)*, 779-788.
<https://doi.org/10.1109/CVPR.2016.91>. arXiv:1506.02640.

[8] Akyon, F. C., Altinuc, S. O., & Temizel, A. (2022). Slicing Aided Hyper
Inference and Fine-tuning for Small Object Detection. *2022 IEEE International
Conference on Image Processing (ICIP)*.
<https://doi.org/10.1109/ICIP46576.2022.9897990>. arXiv:2202.06934.

[9] Neubeck, A., & Van Gool, L. (2006). Efficient Non-Maximum Suppression.
*18th International Conference on Pattern Recognition (ICPR'06)*, 850-855.
<https://doi.org/10.1109/ICPR.2006.479>.

[10] Jaccard, P. (1901). Etude comparative de la distribution florale dans une
portion des Alpes et du Jura. *Bulletin de la Societe Vaudoise des Sciences
Naturelles*, 37, 547-579.

[11] Tukey, J. W. (1977). *Exploratory Data Analysis.* Addison-Wesley.

[12] Astola, J., & Kuosmanen, P. (1997). *Fundamentals of Nonlinear Digital
Filtering.* CRC Press.

[13] Anand, P., Cheong, D., & Sekhar, C. (2022). A review of occupancy-based
building energy and IEQ controls and its future post-COVID. *Science of the
Total Environment*, 804, 150249.
<https://doi.org/10.1016/j.scitotenv.2021.150249>.

### Software libraries and APIs

[14] OpenCV. *cv::VideoCapture Class Reference.*
<https://docs.opencv.org/4.x/d8/dfe/classcv_1_1VideoCapture.html> (accessed
2 November 2026).

[15] Python Software Foundation. *threading - Thread-based parallelism.*
<https://docs.python.org/3/library/threading.html> (accessed 2 November 2026).

[16] Python Software Foundation. *statistics.median.*
<https://docs.python.org/3/library/statistics.html#statistics.median> (accessed
2 November 2026).

[17] Python Software Foundation. *math.floor.*
<https://docs.python.org/3/library/math.html#math.floor> (accessed
2 November 2026).

[18] Pallets Projects. *Flask documentation.*
<https://flask.palletsprojects.com/> (accessed 2 November 2026).

[19] PySerial. *pySerial documentation.*
<https://pyserial.readthedocs.io/> (accessed 2 November 2026).

[20] Python Cryptographic Authority. *cryptography documentation.*
<https://cryptography.io/> (accessed 2 November 2026).

[21] pytest. *pytest documentation.*
<https://docs.pytest.org/> (accessed 2 November 2026).

### Sample asset

[22] Ultralytics. *bus.jpg sample image.*
<https://ultralytics.com/images/bus.jpg> (accessed 2 November 2026). This is
the sample image distributed with the Ultralytics repository and is used under
the AGPL-3.0.

---

## 2. Code provenance map

### `detector.py` - main camera-detection code

| Function / section | Lines | Origin and exact source |
|---|---:|---|
| Module design (tiled detection, full-frame anchor, edge rejection) | 1-17, 207-243 | **Original project design.** The idea of slicing an image for small-object detection is inspired by SAHI [8], but the tiling layout, full-frame pass, and edge-rejection rule are project-specific. The SAHI package is not imported. |
| `_iou(a, b)` | 26-39 | **Original implementation of the Jaccard index** [10]. Intersection area divided by union area. Not copied from Ultralytics. |
| `_contained(a, b)` | 42-79 | **Original project heuristic** for face/hand/limb boxes inside a body box. Uses an intersection-over-smaller-area ratio and a size-ratio guard. No external code. |
| `_part_of(small, large)` | 82-119 | **Original project heuristic** for a body part detected as a separate person. Uses height ratio, aspect ratio, centre-line margin, and vertical position. No external code. |
| `_same_person(a, b)` | 122-147 | **Original merge rule.** Combines containment, body-part, IoU, and centre-distance tests. The IoU threshold is project-tuned. |
| `_area(box)` | 150-152 | **Original helper.** |
| `_merge(boxes)` | 155-161 | **Original greedy merge.** It is not a standard NMS implementation; it keeps the largest full-body box per person. NMS is used only inside the Ultralytics model call. The general NMS concept is covered by [9]. |
| `PersonDetector.__init__` | 167-179 | **Original class.** Loads the model through the documented Ultralytics `YOLO` API [1], [6]. |
| `PersonDetector._predict` | 181-205 | **Original wrapper around `YOLO.predict`.** It requests class 0 (person), confidence, NMS IoU, and image size, then converts `box.xyxy` / `box.conf` to project dictionaries. API source: [1], [6]. |
| `PersonDetector._detect_tiled` | 207-243 | **Original tiled inference.** Calls `_predict` on the full frame and on overlapping 2x2 tiles. The slicing concept is inspired by [8]; the code is not copied from SAHI. |
| `PersonDetector._touches_inner_edge` | 245-259 | **Original project rule.** Rejects boxes clipped by an inner tile border. |
| `PersonDetector.detect` | 261-265 | **Original public API.** Chooses single-pass or tiled detection. |

**Summary:** `detector.py` is original project code. It calls the Ultralytics
YOLO API and implements standard IoU/NMS ideas and a SAHI-inspired tiling
concept. No Ultralytics or SAHI source file is copied.

### `camera.py` - newest-frame reader

| Function / section | Lines | Origin and exact source |
|---|---:|---|
| `_normalise_source` | 47-54 | **Original helper.** Converts a numeric string to a webcam index. |
| `apply_transform` | 57-72 | **Original wrapper** around OpenCV `cv2.flip` and `cv2.rotate` [14]. The orientation modes are project-defined. |
| `LatestFrameReader` | 75-269 | **Original class.** Uses OpenCV `VideoCapture` [14] and Python `threading` [15]. The latest-frame-only design, reconnect loop, file pacing, and restart event are project-specific. |

**Summary:** `camera.py` is original project code built on documented OpenCV
and Python threading APIs. No external reader implementation is copied.

### `config.py` - settings and pure rules

| Function / section | Lines | Origin and exact source |
|---|---:|---|
| `round_half_up(x)` | 13-19 | **Original project helper.** Implements the project's half-up rounding rule with `math.floor(x + 0.5)` [17]. The rule is defined in the report, not copied from a library. |
| Vision constants | 26-38 | **Project-tuned values.** Confidence, IoU, image size, tile count, overlap, class id, and split fractions were selected for this project. |
| Control constants | 45-51 | **Project specification.** Report Sections 5.2 and 5.4-5.6. |
| Camera constants | 58-83 | **Project-tuned values** for the demo laptop and phone stream. |
| Overlay constants | 89-109 | **Project-tuned drawing values** for the OpenCV demo window. |
| `fan_pct(total)` | 116-124 | **Original implementation of the project fan rule:** `min(100, 20 + 8 * total)` while occupied. Formula source: report Section 5.5. Not an external formula. |
| `vent_pct(counts, maxc)` | 131-147 | **Original implementation of the project vent rule:** `round_half_up(15 + 85 * c_i / maxc)`. Formula source: report Section 5.4. Not an external formula. |
| `total_count(counts)` | 154-156 | **Original helper.** |

**Summary:** the formulas are project-defined in the report. The only external
API is `math.floor` [17]. No ASHRAE or manufacturer formula is copied.

### `zones.py` - feet-point zones and median smoothing

| Function / section | Lines | Origin and exact source |
|---|---:|---|
| `MedianSmoother` | 41-61 | **Original wrapper.** Uses Python `statistics.median` [16]. The median-filter concept and its robustness to outliers are covered by [11] and [12]. This is not Tukey's median polish and not a copied filter implementation. |
| `DEFAULT_ZONES` | 68-77 | **Original project geometry.** A 2x2 grid in normalised coordinates. |
| `Zones.__init__` | 88-130 | **Original loader** for the default grid and optional `zones.json`. |
| `Zones._point_in_polygon` | 132-144 | **Original wrapper** around OpenCV `cv2.pointPolygonTest` [5]. |
| `Zones.assign` | 146-179 | **Original assignment rule.** Uses the bottom-centre ("feet") point and tests zones in A, B, C, D order. Point-in-polygon operation: [5]. |
| `Zones.assign_detections` | 181-195 | **Original counting helper.** |
| `Zones.draw` | 197-225 | **Original overlay code** using OpenCV drawing primitives. |

**Summary:** `zones.py` is original project code. The point-in-polygon test is
an OpenCV API call [5]; the median is Python's `statistics.median` [16].

### `main.py` - CLI demo

| Section | Lines | Origin |
|---|---:|---|
| Argument parser | 29-80 | **Original** using Python `argparse`. |
| Image mode | 159-180 | **Original.** Reads with OpenCV, runs the detector, draws the overlay, writes `out_<name>.jpg`. |
| Stream mode | 207-336 | **Original.** Uses `LatestFrameReader`, `PersonDetector`, and `MedianSmoother`. |
| Window keys / display | 89-156, 183-204 | **Original** OpenCV drawing and key handling. |
| Entry point | 339-371 | **Original.** |

**Summary:** `main.py` is original project code. No external CLI or demo source
is copied.

### `control.py` - pure control functions

| Function / class | Lines | Origin |
|---|---:|---|
| `vent_percentages` | 19-40 | **Original implementation** of report Section 5.4. |
| `fan_percent` | 43-60 | **Original implementation** of report Section 5.5. |
| `Controller` | 63-122 | **Original state machine** for the 5 s empty-room hold and IDLE transition. Report Section 5.6. |

**Summary:** the control equations and state machine are project-defined. The
occupancy-based HVAC literature [13] is background motivation, not the source
of these equations.

### `serial_link.py` - laptop-to-ESP32 link

| Section | Lines | Origin |
|---|---:|---|
| XOR checksum helpers | 38-51 | **Original project protocol.** |
| `DummyLink` | 58-85 | **Original** no-hardware fallback. |
| `SerialLink` | 92-308 | **Original** using PySerial [19]. Port auto-detection, `V,...` line format, 5 Hz send period, and fallback behaviour are project-defined. Report Section 7. |

**Summary:** the serial protocol is project-defined. PySerial is the only
external API used.

### `pipeline.py` and `server.py` - dashboard prototype

| Section | Origin |
|---|---|
| `Pipeline` | **Original glue code** for the dashboard path. It combines the detector, zone assignment, median smoothing, and controller. |
| `server.py` Flask routes | **Original application code** using Flask [18]. The dashboard HTML/CSS/JS is project-written. |
| Optional HTTPS path | The dependency `cryptography` [20] is listed for certificate work. The current snapshot does not contain a production HTTPS server. |

**Summary:** these files are a prototype, not part of the verified `main.py`
path. They are included so the design can be reviewed and completed.

### Tests and build files

| File | Origin |
|---|---|
| `tests/test_control.py` | **Original tests** for the report's control vectors (Section 5.8). Uses pytest [21]. |
| `tests/test_zones.py` | **Original tests** for quadrant assignment, feet-point logic, unzoned points, and median smoothing. Uses pytest [21]. |
| `tests/bus.jpg` | **Ultralytics sample image** [22], AGPL-3.0. |
| `requirements.txt` | Package names from the official documentation of each dependency [1], [14], [18], [19], [20], [21]. |
| `requirements-lock.txt` | Exact versions from the tested environment. |

### Documentation

| File | Origin |
|---|---|
| `README.md` | Original project documentation. |
| `REFERENCES.md` | This file. |
| `THIRD_PARTY_NOTICES.md` | Original notices, with licence facts from each dependency. |
| `smart-hvac-final-report.md` | Original project report. |
| `DEMO_RUNBOOK.md` | Original demo procedure. |
| `esp32/README.md` | Original summary of the firmware design in report Sections 7-8. |

---

## 3. What is original, and what is not

### Original project work

- The tiled person-detection pipeline, including the full-frame anchor,
  inner-edge rejection, and custom duplicate/body-part merge.
- The latest-frame camera reader, reconnect logic, and orientation control.
- The feet-point zone assignment and per-zone median smoothing wrapper.
- The vent/fan control equations, half-up rounding rule, IDLE hold, and serial
  protocol.
- The CLI demo, tests, documentation, and the system design in the report.

### External material used

- **Ultralytics YOLO11** for person detection, under AGPL-3.0 [1], [6].
- **COCO-pretrained YOLO11n weights**, downloaded by Ultralytics or supplied
  locally, under AGPL-3.0 [6].
- **OpenCV** for capture, image transforms, drawing, and point-in-polygon
  testing [5], [14].
- **NumPy** for array handling (standard dependency of OpenCV and the
  detector).
- **Flask** for the dashboard prototype [18].
- **PySerial** for the ESP32 link [19].
- **cryptography** as an optional dependency for certificate work [20].
- **pytest** for the unit tests [21].
- **Ultralytics `bus.jpg`** as the sample image [22].
- Published algorithm ideas: YOLO [7], SAHI-style slicing [8], NMS [9],
  Jaccard/IoU [10], median filtering [11], [12], and occupancy-based HVAC
  motivation [13].

### Not used / not copied

- The SAHI Python package is not a dependency and its source is not copied.
- The project does not vendor Ultralytics source code; it imports the installed
  package.
- The project does not use a custom-trained model or an external dataset.
- No Stack Overflow, blog, or GitHub snippet is copied into the source files.
- No ASHRAE standard equation is reproduced; the vent/fan rules are project
  specifications.

---

## 4. Licence mapping

| Component | Licence |
|---|---|
| Project source and documentation | AGPL-3.0 (see `LICENSE`) |
| Ultralytics YOLO11 and YOLO11n weights | AGPL-3.0 [4], [6] |
| Ultralytics `bus.jpg` sample | AGPL-3.0 [22] |
| OpenCV | Apache-2.0 |
| NumPy | BSD-3-Clause |
| Flask | BSD-3-Clause |
| PySerial | BSD-3-Clause |
| cryptography | Apache-2.0 OR BSD-3-Clause |
| pytest | MIT |
| Python | PSF-2.0 |

See [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) for the full notices.

---

## 5. How to cite this project

If you refer to this work academically, cite the repository and the report:

```text
Smart HVAC project. Smart HVAC - Camera-Based Zone Occupancy.
GitHub repository, 2026. https://github.com/bhuvan-cmyk/Smart-HVAC
```

Also cite Ultralytics YOLO11 [6] and the algorithm papers that your text uses.
