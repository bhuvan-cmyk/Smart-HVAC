# Model weights

The model weights are **not committed to this repository**. They are large
binary files and are not part of the source code review.

## Default behaviour

`detector.py` looks for `models/yolo11n.pt` first. If it is missing, it falls
back to the model name `yolo11n.pt`, and the Ultralytics package downloads the
COCO-pretrained YOLO11n weights automatically on first use.

The project was tested with:

```text
models/yolo11n.pt
ultralytics==8.4.190
```

## Offline setup

If the demo laptop will not have internet access, download the weights once
while online and place the file here:

```text
models/yolo11n.pt
```

Then run normally. `config.MODEL_PATH` already points to that file.

## Licensing

YOLO11 and the YOLO11n weights are distributed by Ultralytics under the
**GNU Affero General Public License v3.0 (AGPL-3.0)**. See
[`../THIRD_PARTY_NOTICES.md`](../THIRD_PARTY_NOTICES.md) and
[`../LICENSE`](../LICENSE).

A commercial Ultralytics licence is required if you integrate the model into a
closed-source product or service. See <https://www.ultralytics.com/license>.

## Why the OpenVINO export is not here

`models/yolo11n_openvino_model/` is a generated export and is intentionally
ignored. Regenerate it only if you need the OpenVINO runtime:

```bat
yolo export model=models\yolo11n.pt format=openvino
```
