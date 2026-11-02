# Third-party notices

This project is released under the **GNU Affero General Public License v3.0
(AGPL-3.0)**. It uses the following third-party software, model weights, and
assets. The notices below are provided for attribution and licence compliance.

The authoritative licence text for this project is in [`LICENSE`](LICENSE).

---

## Ultralytics YOLO11

- **Used for:** person detection (`detector.py`), pretrained YOLO11n weights.
- **Project:** <https://github.com/ultralytics/ultralytics>
- **Documentation:** <https://docs.ultralytics.com/models/yolo11/>
- **Licence:** GNU Affero General Public License v3.0 (AGPL-3.0).
- **Commercial licensing:** <https://www.ultralytics.com/license>

The project imports the installed `ultralytics` package. It does not vendor
Ultralytics source code. The YOLO11n weights are not committed to this
repository; they are downloaded by Ultralytics on first use or supplied locally
in `models/`.

If you modify this project and make it available as a network service, the
AGPL requires you to offer the corresponding source to users of that service.

---

## Ultralytics sample image (`tests/bus.jpg`)

- **File:** `tests/bus.jpg`
- **Source:** <https://ultralytics.com/images/bus.jpg>
- **Licence:** AGPL-3.0, as distributed with the Ultralytics repository.
- **Purpose:** still-image smoke test for the detector (`People: 4`).

The image contains people in a public street scene. It is used only as a
detection sample; it is not part of the live camera path.

---

## OpenCV

- **Used for:** camera capture, image transforms, drawing, and
  `cv2.pointPolygonTest`.
- **Project:** <https://opencv.org/>
- **Documentation:** <https://docs.opencv.org/4.x/>
- **Licence:** Apache License 2.0.

Key APIs used:

- `cv2.VideoCapture`
- `cv2.flip`, `cv2.rotate`
- `cv2.pointPolygonTest`
- `cv2.rectangle`, `cv2.circle`, `cv2.putText`, `cv2.polylines`
- `cv2.imread`, `cv2.imwrite`, `cv2.imencode`

---

## NumPy

- **Used for:** array handling (directly and through OpenCV).
- **Project:** <https://numpy.org/>
- **Licence:** BSD-3-Clause.

---

## Flask

- **Used for:** the dashboard/phone-camera prototype in `server.py`.
- **Project:** <https://flask.palletsprojects.com/>
- **Licence:** BSD-3-Clause.

The dashboard is a local-network prototype and is not launched by `main.py` in
this snapshot.

---

## PySerial

- **Used for:** the USB serial link to the ESP32 in `serial_link.py`.
- **Project:** <https://pyserial.readthedocs.io/>
- **Licence:** BSD-3-Clause.

---

## cryptography

- **Used for:** optional certificate/TLS work for the phone-browser camera.
- **Project:** <https://cryptography.io/>
- **Licence:** Apache License 2.0 OR BSD-3-Clause.

The current snapshot lists the dependency but does not contain a production
HTTPS server.

---

## pytest

- **Used for:** the unit tests in `tests/`.
- **Project:** <https://docs.pytest.org/>
- **Licence:** MIT.

---

## Python

- **Used for:** the runtime.
- **Project:** <https://www.python.org/>
- **Licence:** Python Software Foundation License 2.0.

---

## ESP32 documentation

The report and `esp32/README.md` refer to the ESP32 hardware and the
Arduino-ESP32 core. No Espressif source code or firmware binary is included in
this snapshot.

- **ESP32 datasheet:** <https://www.espressif.com/en/products/socs/esp32>
- **Arduino-ESP32 documentation:** <https://docs.espressif.com/projects/arduino-esp32/en/latest/>

---

## Reference-only material

The following are cited in [`REFERENCES.md`](REFERENCES.md) but are not
distributed with this repository:

- Redmon et al., *You Only Look Once* (CVPR 2016).
- Akyon et al., *Slicing Aided Hyper Inference* (ICIP 2022).
- Neubeck & Van Gool, *Efficient Non-Maximum Suppression* (ICPR 2006).
- Jaccard (1901), Tukey (1977), Astola & Kuosmanen (1997).
- Anand et al., *A review of occupancy-based building energy and IEQ
  controls* (2022).

These are academic references, not bundled code or data.

---

## Model-weight note

The repository intentionally does not commit:

- `models/yolo11n.pt`
- `yolo11s.pt`
- `models/yolo11n_openvino_model/`
- any other `*.pt`, `*.onnx`, `*.engine`, or `*.tflite` file

If you redistribute the YOLO11n weights, keep the AGPL-3.0 notice and the
Ultralytics attribution with them. The submission ZIP is a separate local
artifact and is not part of the Git repository.
