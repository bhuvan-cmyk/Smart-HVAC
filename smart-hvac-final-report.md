# Smart Zone-Based HVAC with Camera Occupancy Counting

**Final-year project report and build specification**

**Version 2.0 · 27 October 2026**

**Status:** final design. The software is implemented and verified in the phases described in Section 10; hardware verification follows when the rig is assembled.

This document is the authoritative specification for the build. Where an older note or a piece of code disagrees with it, this document defines the intended behaviour.

---

## Abstract

Conventional HVAC systems condition a room as a single well-mixed volume. When occupancy is uneven, this supplies air to empty areas and under-serves crowded ones, wasting fan energy and reducing comfort. This project develops a low-cost, camera-based, occupancy-aware HVAC controller for a room divided into four zones. A phone camera or fixed IP camera supplies video to a laptop, where YOLO11n detects people. Each detection is assigned to a zone using the bottom-centre of its bounding box, and a median filter stabilises the per-zone counts. The laptop computes each vent opening from the zone's share of the busiest zone, and fan speed from total occupancy. The resulting percentages are sent over USB serial to an ESP32, which converts them into servo angles and fan PWM, limits the rate of movement, and enters a safe state if valid commands stop for 10 s. A browser dashboard shows the live result, and a simulator exercises the same control and serial path without hardware. This report defines the architecture, control equations, vision pipeline, serial protocol, firmware, power design, test plan, limitations, and privacy position. No camera frames are stored.

**Keywords:** occupancy sensing, computer vision, YOLO, zone control, HVAC, ESP32, fail-safe control, privacy.

---

## 1. Introduction

### 1.1 Problem statement

Buildings are usually ventilated and conditioned as single well-mixed volumes. This is adequate when occupancy is uniform, but it is inefficient and uncomfortable when one part of a room is crowded while another is empty. Uniform control delivers the same airflow everywhere, so crowded zones are under-served and empty zones receive air they do not need. The fan also runs at the same duty whether the room contains ten people or none.

Occupancy-aware zoning can reduce this mismatch, but it requires a sensing method that is low-cost, unobtrusive, and reliable enough for control. Cameras are attractive because one view can cover several zones without wearable tags or seat switches. The engineering problem is not detection alone. Per-frame detections are noisy, people overlap, zone boundaries depend on camera perspective, and a controller that acts on stale or failed sensing can leave the vents in an unsafe position. The project therefore addresses the complete chain: detect, assign, smooth, decide, transmit, actuate, and fail safe.

### 1.2 Aim and research question

**Aim:** to design, build, and evaluate a camera-based controller that adjusts four zone vents and one fan according to the number and distribution of people in a room, while remaining safe when sensing or communication fails.

**Research question:** can a single overhead camera and a lightweight person detector provide zone occupancy estimates accurate enough to drive a four-zone vent system, while keeping the control rule simple, testable, and privacy-preserving?

### 1.3 Objectives

1. Detect people in a live camera stream with a lightweight, CPU-capable model.
2. Assign each person to one of four zones using the feet point of the detection box.
3. Smooth noisy per-zone counts and hold the previous output briefly before declaring the room empty.
4. Compute vent openings from relative zone occupancy and fan speed from total occupancy.
5. Transmit the resulting percentages to an ESP32 that moves four servos and a PWM fan safely.
6. Enter a defined safe state when camera data, the laptop, or the serial link fails.
7. Provide a dashboard and a hardware-free simulator for demonstration and testing.
8. Store no images or video in live operation.

### 1.4 Scope

**In scope:** one room, four fixed zones, a monocular camera, person detection without tracking, a laptop-based control rule, USB serial communication, an ESP32 actuator controller, a browser dashboard, a simulator, unit tests, and the hardware design for the vent box.

**Out of scope for this build:** temperature feedback, CO₂ sensing, cloud or MQTT control, person identification, thermal-comfort modelling, and person tracking across frames. These are treated as future work in Section 14. The hardware rig is built after the software has been verified.

---

## 2. Assumptions and design decisions

### 2.1 Assumptions

| Item | Assumption |
|---|---|
| ESP32 board | Classic ESP32 DevKit (ESP32-WROOM-32), "ESP32 Dev Module" in the Arduino IDE |
| Firmware toolchain | Arduino IDE 2.x with the Arduino-ESP32 core, version 2.x or 3.x; ESP32Servo library |
| Laptop | Windows, Linux or macOS, CPU only, Python 3.10 or newer |
| Detector | Ultralytics YOLO11n (`yolo11n.pt`); a larger Ultralytics detection model may be substituted if the laptop is fast enough |
| Camera | Camera (phone for the demo, fixed IP camera or webcam for installation), 720p |
| Room | One enclosed room with a flat floor and a fixed camera view covering all four zones |
| Demo scale | Real people or full-body standees; dolls and toys are not detected as people |
| Network | Laptop and phone on the same local network, normally the phone's hotspot |

### 2.2 Key design decisions

| Area | Decision | Reason |
|---|---|---|
| Vision placement | Camera → laptop → ESP32; images never reach the ESP32 | A classic ESP32 cannot run a modern person detector at useful accuracy and speed; the laptop has the required compute and memory |
| Control placement | The control rule runs on the laptop; the ESP32 receives vent and fan percentages | One implementation, unit-testable without hardware, and a simple actuator contract |
| Transport | ASCII percentages, not raw counts, over USB serial | The ESP32 does not need zone logic; percentages are the complete command |
| Vent minimum | 15 % while the room is occupied | A running fan against fully closed vents builds pressure and provides no ventilation; the value is configurable |
| Empty room | Idle mode: vents closed, fan at minimum PWM. A relay on the 12 V line is the optional full cut-off. | A 4-pin fan may keep spinning at 0 % PWM; the relay is the only true stop |
| Occupancy estimate | Median of the last 5 samples per zone, plus a 5 s empty-room hold | A single missed or spurious detection must not move a vent; the hold prevents chatter at zero |
| Vent scaling | 15 + 85 × (zone count ÷ busiest zone's count) | The busiest zone opens fully; quieter zones open proportionally |
| Fan scaling | 20 + 80 × (total ÷ 10), capped at 100 % | The fan reaches full speed at 10 people and never drops below 20 % while occupied |
| Rounding | Round half up with `floor(x + 0.5)` | Python's `round()` uses banker's rounding and would make the laptop and firmware disagree |
| Failsafe | Send only while the newest frame is under 3 s old; ESP32 enters SAFE after 10 s without a valid command | A frozen camera or crashed laptop must not leave stale commands in control |
| Boot state | ESP32 starts in BOOT with vents closed and fan at 0 %, then goes to NORMAL on the first valid command or SAFE after 10 s | The actuator state is known before the laptop connects |
| Serial validation | Exactly six integer fields, each 0–100; invalid lines are rejected and reported with `E,<reason>` | A short, strict parser is sufficient for a local USB link; the watchdog remains the primary safety mechanism |
| Servo power | Separate 5 V rail rated at least 3 A; 5 A recommended if servos jitter | Four SG90 servos can draw about 2.6 A at stall; 3 A is a minimum, not a comfortable margin |
| Privacy | No frames written to disk or sent to a cloud service | The system counts boxes, not identities, and the dashboard is local to the room network |

---

## 3. System overview

### 3.1 One scenario, two views

| Moment | User perspective | Engineering perspective |
|---|---|---|
| Room is empty | Idle mode: vents closed, fan at minimum PWM. A relay on the 12 V line is the optional full cut-off. | Counts are 0,0,0,0 for 5 s. The controller enters IDLE; vents are 0 %, fan command is 0 % (minimum PWM) |
| 3 people sit in zone B | Fresh air reaches them within a few seconds | Counts 0,3,0,0. Vent B 100 %, others 15 %. Fan 44 % |
| 5 more join zone D | Both groups receive air; the larger group receives more | Counts 0,3,0,5. D 100 %, B 66 %, A and C 15 %. Fan 84 % |
| 2 more join zone A | The room is at the design occupancy | Counts 2,3,0,5. A 49 %, B 66 %, C 15 %, D 100 %. Fan 100 % |
| People leave | Air quietens gradually, without a sudden change | Counts fall after smoothing. Vents and fan ramp down. After 5 s of confirmed zero, IDLE |
| Camera or cable fails | The room remains in a defined, comfortable state | No valid command for 10 s. ESP32 enters SAFE: all vents 50 %, fan 30 % |

**User view in one line:** nobody touches anything; the room gives more air to crowded areas and saves fan energy when it is empty.

**Engineering view in one line:** camera → laptop (YOLO, zones, control) → USB serial percentages → ESP32 (angles, PWM, watchdog) → vents and fan.

### 3.2 Block responsibilities

| Block | Job |
|---|---|
| Camera | Captures the room from a high corner or wall; performs no detection and stores nothing |
| Laptop program | Detects people, assigns zones, smooths counts, applies the control rule, serves the dashboard, sends percentages, logs numbers |
| ESP32 | Converts vent and fan percentages into servo angles and PWM, moves them slowly, runs the 10 s failsafe, reports status |
| 4 servos | Move one flap per vent |
| Fan | Pushes air into a plenum box with four outlets |
| Power | 12 V for the fan; a separate regulated 5 V rail for the servos |

---

## 4. Architecture and data flow

### 4.1 Data flow

```text
Camera (phone for the demo, fixed IP camera or webcam for installation)
   │  Wi-Fi hotspot, USB, or HTTPS upload
   ▼
LAPTOP (Python)
   ├─ latest-frame capture      : keeps only the newest frame
   ├─ YOLO11n detector          : person class only, about 5 frames/s
   ├─ zone assignment           : bottom-centre of box (feet) → A/B/C/D
   ├─ median smoothing          : 5 samples per zone
   ├─ control rule              : vent percentages, fan percentage
   ├─ dashboard                 : web page on :8000, phone camera on :8443
   ├─ logging                   : numeric CSV only
   └─ serial link               : V,A,B,C,D,FAN at 5 Hz
             │  USB serial, 115200 baud, ASCII lines
             ▼
ESP32
   ├─ strict parser             : six integers, 0–100
   ├─ percentage → servo angle
   ├─ slew limiter              : 20 ms update, 1° and 1 % steps
   ├─ watchdog                  : 10 s without a valid line → SAFE
   ├─ status line               : S,MODE,angles,fan once per second
   └─ outputs                   : 4 × servo PWM, fan PWM, status LED,
                                  optional relay on the 12 V line
             │                         │
        4 vent flaps              12 V 4-pin fan → plenum box
```

The ESP32 reports its actual state once per second. The dashboard displays that state, so the audience sees the actuator result rather than only the laptop's requested values.

### 4.2 Why the camera is not connected to the ESP32

An early version of the brief placed the camera directly on the ESP32. The final design is camera → laptop → ESP32, and this change is deliberate. A classic ESP32 has neither the memory nor the compute to run a modern person detector at useful accuracy and speed. Running detection on the microcontroller would also mix vision workloads with servo timing and the failsafe in one small device, making the safety case harder to guarantee. The laptop therefore performs detection, zone assignment, smoothing, and the control rule; the ESP32 remains the real-time actuator and failsafe controller. Only six integers cross the serial link. No frames, crops, or video are sent to the ESP32.

### 4.3 Why the control rule runs on the laptop

The earlier design had the ESP32 turn counts into vent angles. In the final design the rule lives in one place, on the laptop, and the ESP32 receives already-computed percentages. This has three benefits. First, the rule can be unit-tested and demonstrated with no hardware. Second, the dashboard, the simulator, and the real system all execute the same code. Third, the ESP32 firmware stays small: it validates a percentage line, maps percentages to angles, limits motion, and runs the watchdog. The ESP32 still owns the 10 s failsafe, so a laptop failure cannot leave the vents in an arbitrary state.

---

## 5. Control specification (binding)

### 5.1 Symbols

- `cA, cB, cC, cD` — smoothed counts in zones A–D.
- `u` — people detected outside all zones.
- `N = cA + cB + cC + cD + u` — total occupancy used for fan control.
- `cmax = max(cA, cB, cC, cD)` — count in the busiest zone.
- `vi` — vent opening for zone `i`, in percent.
- `F` — fan command, in percent.
- `round_half_up(x) = floor(x + 0.5)`.

All commands sent to the ESP32 are integers from 0 to 100.

### 5.2 Parameters

| Name | Value | Meaning |
|---|---|---|
| `ZONES` | 4 | A, B, C, D = indices 0, 1, 2, 3 |
| `VENT_MIN` | 15 | Minimum vent opening while the room is occupied |
| `VENT_MAX` | 100 | Fully open vent |
| `FAN_MIN` | 20 | Fan speed at the lowest occupied count |
| `FAN_MAX` | 100 | Maximum fan speed |
| `FAN_FULL_AT` | 10 | Total occupancy at which the fan reaches 100 % |
| `FAN_IDLE` | 0 | Fan command in IDLE (minimum PWM) |
| `IDLE_DELAY_S` | 5 | Time at zero occupancy before IDLE is confirmed |
| `SMOOTH_WINDOW` | 5 | Median window per zone |
| `SAFE_VENT_PCT` | 50 | Vent opening in SAFE |
| `SAFE_FAN_PCT` | 30 | Fan speed in SAFE |
| `WATCHDOG_MS` | 10000 | No valid serial command for this long means SAFE |
| `SEND_PERIOD_S` | 0.2 | Laptop sends at 5 Hz |
| `FRAME_FRESH_S` | 3 | Commands are sent only while the newest frame is younger than this |
| `CONTROL_TICK_MS` | 20 | ESP32 update period |
| `SERVO_STEP_DEG` | 1 | Maximum servo movement per control tick |
| `FAN_STEP_PCT` | 1 | Maximum fan change per control tick |
| `STATUS_PERIOD_MS` | 1000 | ESP32 status line interval |

`FAN_MIN` applies while the room is occupied. In IDLE the fan command is `FAN_IDLE = 0`, which is the minimum PWM setting. Many 4-pin fans continue to turn at 0 % PWM; the optional relay provides a true electrical cut-off.

### 5.3 Zone assignment

Zones are polygons in normalised frame coordinates (0–1 in both axes). The default is a 2 × 2 grid:

- A: top-left
- B: top-right
- C: bottom-left
- D: bottom-right

The split is controlled by `ZONE_SPLIT_X = 0.5` and `ZONE_SPLIT_Y = 0.5`. An optional `zones.json` file replaces the grid with four polygons, which allows the zones to match the room rather than the image.

A person belongs to the zone containing their **feet point**:

```text
feet = ((x1 + x2) / 2, y2)
```

This is the bottom-centre of the detection box. The box centre is not used because a high camera angle shifts the apparent centre upwards. The point is tested with `cv2.pointPolygonTest` [5]. A point on a shared edge belongs to the first zone in the order A, B, C, D.

A feet point outside every polygon is counted in `u` and therefore contributes to `N`, but it belongs to no zone. If the room is occupied but every zone count is zero, all vents take the 15 % minimum; this avoids division by zero and prevents a running fan from working against four closed vents.

### 5.4 Vent rule

Let `counts = [cA, cB, cC, cD]`. The rule is:

```text
If N = 0 and the room has been empty for 5 s:
    vi = 0 for all zones.

Else if cmax = 0:
    vi = 15 for all zones.

Else:
    vi = round_half_up(15 + 85 × ci / cmax)
```

In words: **Vent % = 15 + 85 × (zone count ÷ busiest zone's count), and 0 % once the room has been empty for 5 s.** The busiest zone always reaches exactly 100 %. An occupied zone with no people receives exactly 15 %. The 5 s hold is implemented by the controller (Section 5.6); the pure function returns the formula result for the counts it is given.

Example: with counts `0,3,0,5`, the busiest zone is D with 5 people. Zone B receives `15 + 85 × 3/5 = 66 %`, zone D receives 100 %, and zones A and C receive 15 %.

### 5.5 Fan rule

```text
If N = 0 and the room has been empty for 5 s:
    F = 0.

Else:
    F = min(100, round_half_up(20 + 80 × N / 10))
```

In words: **Fan % = 20 + 80 × (total ÷ 10), capped at 100.** Because `N` is an integer, the result is simply `min(100, 20 + 8N)` while occupied.

| Total people `N` | 0 | 1 | 3 | 4 | 5 | 8 | 10 | 12 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Fan `%` | 0 (IDLE) | 28 | 44 | 52 | 60 | 84 | 100 | 100 |

The formula applies while the room is occupied. At confirmed zero occupancy the controller enters IDLE and commands the fan to minimum PWM. A relay on the 12 V line is the optional full cut-off.

### 5.6 Smoothing and the empty-room hold

1. Each zone has a median smoother over the last 5 samples (about 1 s at 5 detections per second).
2. A single missed or spurious detection cannot change a median of 5 by itself.
3. When the smoothed total becomes zero, the controller holds the previous vent and fan outputs for `IDLE_DELAY_S = 5 s`. If people reappear, normal control resumes immediately and the hold is cancelled.
4. If the total remains zero for 5 s, the controller enters IDLE: vents closed, fan at minimum PWM.
5. Vent and fan targets are sent as percentages. The ESP32 applies its own slew limit, so the physical motion is always slower than the command change.

The median is applied per zone, not to the total. This matters when people move between zones: a person crossing a boundary should not briefly open both vents to full.

### 5.7 Modes

| Mode | Entered when | Vents | Fan |
|---|---|---|---|
| **NORMAL** | `N ≥ 1` | Rule 5.4 | Rule 5.5 |
| **IDLE** | `N = 0` for 5 s | 0 % | 0 % (minimum PWM) |
| **SAFE** | ESP32 has received no valid command for 10 s, or the 10 s boot timeout expires | 50 % | 30 % |

The single IDLE definition used throughout this report is: **Idle mode: vents closed, fan at minimum PWM. A relay on the 12 V line is the optional full cut-off.**

The laptop controller implements NORMAL and IDLE. The ESP32 implements BOOT, NORMAL, and SAFE. The dashboard displays NORMAL or IDLE from the laptop and SAFE from the ESP32; if the ESP32 link is lost, it displays `LINK LOST` rather than pretending the actuators are known.

SAFE overrides everything on the ESP32. The next valid `V` line returns the firmware to NORMAL. A valid line with all zeros returns the system to IDLE through the laptop's 5 s hold.

### 5.8 Control test vectors

These vectors assume no unzoned people and no idle hold; they test the pure control functions. The column order is `A,B,C,D → vent A, vent B, vent C, vent D, fan`.

| A | B | C | D | Vent A | Vent B | Vent C | Vent D | Fan |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 0 | 3 | 0 | 0 | 15 | 100 | 15 | 15 | 44 |
| 0 | 3 | 0 | 5 | 15 | 66 | 15 | 100 | 84 |
| 1 | 1 | 1 | 1 | 100 | 100 | 100 | 100 | 52 |
| 0 | 0 | 0 | 1 | 15 | 15 | 15 | 100 | 28 |
| 12 | 0 | 0 | 0 | 100 | 15 | 15 | 15 | 100 |
| 1 | 2 | 0 | 2 | 58 | 100 | 15 | 100 | 60 |
| 5 | 2 | 1 | 0 | 100 | 49 | 32 | 15 | 84 |
| 7 | 1 | 0 | 0 | 100 | 27 | 15 | 15 | 84 |
| 10 | 0 | 0 | 0 | 100 | 15 | 15 | 15 | 100 |

`1,2,0,2` includes a half-percent case: zone A is `15 + 85 × 1/2 = 57.5`, which rounds half up to 58. This vector catches the use of Python's banker's rounding.

### 5.9 Timing

| Action | Rate |
|---|---|
| Camera capture | continuous, newest frame only |
| Detection | about 5 frames per second |
| Control and serial send | 5 Hz (`SEND_PERIOD_S = 0.2`) |
| ESP32 control tick | 50 Hz (`CONTROL_TICK_MS = 20`) |
| ESP32 status line | 1 Hz |
| Dashboard state poll | 2 Hz |

A command is sent only if a frame younger than 3 s has been processed since the last send. If the camera is lost, the laptop stops sending and the ESP32 reaches SAFE after 10 s.

---

## 6. Vision system

### 6.1 Camera sources

| Source | How it is given | Typical use |
|---|---|---|
| iPhone with DroidCam | `http://PHONE_IP:4747/video` | Demo and temporary installation (used in this build) |
| Android phone with IP Webcam | `http://PHONE_IP:8080/video` | Demo and temporary installation |
| Phone browser | `https://LAPTOP_IP:8443/camera` | No-app demo on Android and iPhone |
| Fixed IP camera | HTTP or RTSP stream URL | Permanent installation |
| USB webcam | Webcam index (`0`, `1`, …) | Installation or backup |
| Recorded video | File path, looped | Demo fallback and repeatable tests |
| No camera | `--sim` | Software demonstration without hardware |

The block diagram uses the generic label **Camera (phone for the demo, fixed IP camera or webcam for installation)**; all three are supported without changing the rest of the pipeline.

For phone use, join the laptop to the phone's hotspot rather than relying on college Wi-Fi, which often blocks device-to-device traffic. Set the camera to the highest resolution the app offers (1080p if available, otherwise 720p), keep the phone charged and its screen on, disable Auto-Lock, and keep DroidCam in the foreground. Mount it on a tripod or fixed holder. The iPhone stream is delivered sideways; the program corrects it with `CAMERA_ROTATE = 90`. Only the camera link is wireless; the ESP32 remains on the USB cable.

### 6.2 Detector

The detector is Ultralytics YOLO11n [1], using the Ultralytics implementation [6], run on the laptop CPU. The whole frame is resized to 640 px, which makes people at the back of a classroom very small, so the detector runs on the full frame **and** on four overlapping tiles, then merges the results. The slicing idea is inspired by SAHI [8]; the tiling layout, full-frame anchor, and edge-rejection rule are project-specific.

| Setting | Value |
|---|---|
| Model | `models/yolo11n.pt`, falling back to the name `yolo11n.pt` |
| Person class | 0 |
| Confidence | 0.25 |
| NMS IoU | 0.70 |
| Input size | 640 |
| Tiling | 2 × 2 tiles, 25 % overlap |
| Full-frame pass | yes, as an anchor for people on a tile border |
| Processed rate | about 1–1.5 frames per second on the demo laptop |

Only class 0 (person) is requested. The model path is local so the demo works on a phone hotspot without internet; the weights are downloaded once while online. Intersection-over-union is the Jaccard index [10], and the model's internal non-maximum suppression is the standard method described by Neubeck and Van Gool [9].

Two post-processing rules keep the count correct:

1. **Tile-edge fragments are discarded.** A box touching an inner tile border is a cut-off face, hand, or half-body. The adjacent overlapping tile or the full-frame pass sees the whole person.
2. **Duplicates are merged, different people are not.** Boxes merge when their IoU is at least 0.55, when a small fragment is contained in a body box, or when a limb-shaped box belongs to the lower body. Two people of similar size who overlap are kept as two.

The thresholds were chosen from measured failures: without tile-edge rejection, `tests/bus.jpg` overcounts 4 people as 7; without the full-frame anchor it undercounts them as 1. On a 16-person portrait stress scene, 416 px found 7, 640 px found 11, and 640 px with 2 × 2 tiles found 14–15.

### 6.3 Latest-frame capture

A background thread reads the camera continuously and keeps only the newest frame and its timestamp. This prevents a stream from building up several seconds of latency while the detector is busy. The capture buffer is set to one frame, and the reader reconnects every 2 s after a failure; video files loop at their natural frame rate. The rest of the program never blocks on a camera read.

The iPhone DroidCam stream is delivered sideways, so a 90° clockwise rotation is applied as each frame is read (`CAMERA_ROTATE = 90`). The detector and the display use the same transform, so boxes line up with the image. Without it, the best person confidence on the test frame fell from 0.96 to 0.08.

Network opens and reads carry explicit timeouts (5 s open, 3 s read). If a frame is older than 3 s the UI reports `camera LOST`; after 5 s without a frame the reader requests a non-blocking reopen. A dropped stream therefore recovers without freezing the window or reporting a stale count. In testing, a killed stream was detected at 6.4 s and recovered 1.0 s after the server returned; a mid-demo drop recovered in about 3 s.

### 6.4 Zone overlay

The annotated frame shows:

- green person boxes;
- a dot at each person's feet point;
- zone outlines and the letters A–D;
- the smoothed count in each zone;
- a large total count and the camera/link status.

These overlays are diagnostic. They are drawn on the in-memory frame and on the browser stream; they are never written to disk in live mode.

### 6.5 Dashboard, phone camera, and simulator

The laptop serves a Flask dashboard on `0.0.0.0:8000`:

| Route | Content |
|---|---|
| `/` | Single-page dashboard: live annotated video, giant total, per-zone counts, vent bars, fan, mode, LIVE/LOST badge, FPS |
| `/video` | MJPEG stream of the latest annotated JPEG |
| `/state` | JSON state for the 2 Hz dashboard poll |
| `/sim` | POST endpoint for the simulator controls |

The page is dark-themed and mobile-friendly. On start the program prints the LAN URL, for example `http://LAPTOP_IP:8000`, using the UDP-socket trick to find the laptop's address.

With `--https`, the same app is also served on port 8443 using a self-signed certificate. The `/camera` page requests the rear phone camera with `getUserMedia`, draws each frame to a canvas at a maximum width of 640 px, sends it as a JPEG to `/upload`, and waits for the JSON reply before sending the next frame. This sequential design prevents a backlog. The reply contains the total and normalised boxes, which are drawn on an overlay canvas. The page works on Android and iPhone without an app. Because the certificate is self-signed, the phone shows a warning; the user chooses **Advanced → Proceed**.

The simulator (`--sim --port dummy`) uses the same controller and serial path. The dashboard shows `+` and `−` buttons per zone and a Reset button. In the local OpenCV window, keys `1`–`4` add one person to zones A–D and `q`, `w`, `e`, `r` remove one. `Esc` quits. This allows the complete control logic to be demonstrated with no camera and no ESP32.

The laptop dashboard mirrors phone-browser frames, so the audience can watch the same result while the phone is being pointed at the room.

### 6.6 Privacy

Live frames exist only in memory. Camera frames, browser uploads, and annotated JPEGs are not written to disk. The CSV log contains counts and state, not images. The full position is stated in Section 13.

---

## 7. Serial protocol

### 7.1 Physical link

The laptop and ESP32 are connected by USB serial at **115200 baud, 8N1, ASCII, newline-terminated**. The protocol carries numbers only; no image data or personally identifying information is transmitted.

Opening the port usually resets the ESP32. The laptop therefore waits 2 s after opening, flushes the input buffer, and then begins sending. The reset is harmless: the firmware starts in BOOT with the vents closed and the fan at 0 %.

### 7.2 Laptop to ESP32

```text
V,<A>,<B>,<C>,<D>,<FAN>
```

- Exactly six comma-separated fields.
- `A`–`D` are vent percentages, 0–100.
- `FAN` is the fan percentage, 0–100.
- All fields are integers.
- The line ends with `\n`.

Example for counts `0,3,0,5`:

```text
V,15,66,15,100,84
```

The rule is deliberately not sent as counts. The laptop has already applied the control equations, so the ESP32 receives the complete actuator demand. This keeps the firmware small and makes the laptop simulator exercise the same path as the real system.

The protocol has no checksum. It is a short local USB link; every line is validated by field count, integer parsing, and range. A malformed or out-of-range line is rejected and reported with `E,<reason>`. The safety mechanism is the watchdog: if valid lines stop, the ESP32 enters SAFE.

### 7.3 ESP32 to laptop

```text
S,<MODE>,<angA>,<angB>,<angC>,<angD>,<fanPct>
E,<reason>
```

- `S` is sent once per second.
- `MODE` is `BOOT`, `NORMAL`, or `SAFE`.
- `angA`–`angD` are the actual servo angles in degrees.
- `fanPct` is the actual fan command, 0–100.
- `E,<reason>` reports a rejected command, for example `E,badline`.

The laptop stores the last `S` line and its time. The ESP32 is considered connected if an `S` line has been seen within 3 s. The dashboard uses these actual values for its vent and fan display.

### 7.4 Boot, reconnect, and watchdog

| Situation | Firmware state | Outputs |
|---|---|---|
| Power-on | BOOT | Vents closed; fan 0 %; watchdog clock starts |
| First valid `V` line | NORMAL | Targets from the line |
| No valid line for 10 s | SAFE | Vents 50 %; fan 30 % |
| Valid line while in SAFE | NORMAL | Targets from the line |
| USB unplugged and reconnected | BOOT, then NORMAL | Closed/0 until the first valid line |

The laptop retries a missing port every 2 s and keeps the dashboard running. If no port can be opened, it falls back to a dummy link that prints the line it would send at most once per second. The software never crashes because the ESP32 is absent.

### 7.5 Failure behaviour

| Failure | How it is detected | Response |
|---|---|---|
| Camera frozen or unplugged | Newest frame becomes older than 3 s | Laptop stops sending; ESP32 enters SAFE after 10 s |
| Laptop program crashes | No serial lines | ESP32 enters SAFE after 10 s |
| USB cable pulled | No serial lines | ESP32 enters SAFE after 10 s; laptop shows disconnected |
| Malformed serial line | Field count, parse, or range check | `E,badline`; last valid state continues until the watchdog expires |
| ESP32 reset | BOOT status line | Vents closed, fan 0 %; first valid line restores NORMAL |
| No serial port at all | Open failure | Dummy link; dashboard and simulator continue |
| Camera absent in simulator | Simulator counts | Same controller and serial path; no camera needed |

This chain is the reason the camera is allowed to be a phone on Wi-Fi: if the phone drops off the network, the actuator side does not keep acting on a stale count.

---

## 8. ESP32 firmware

### 8.1 Role

The ESP32 does not detect people and does not apply the zone rule. It receives a six-integer percentage line, maps vent percentages to servo angles and the fan percentage to PWM, moves all outputs slowly, and runs the 10 s failsafe. This split keeps the time-critical actuator loop small and independent of the vision workload.

### 8.2 Pin map

| Function | GPIO | Notes |
|---|---|---|
| Servo A (vent 0) | 18 | Signal only; power from the separate 5 V rail |
| Servo B (vent 1) | 19 | Signal only |
| Servo C (vent 2) | 21 | Signal only |
| Servo D (vent 3) | 22 | Signal only |
| Fan PWM (4-pin fan, pin 4) | 23 | 25 kHz, 8-bit |
| Status LED | 2 | Onboard LED |
| Fan relay, optional | 27 | Declared in the header but commented out; switches the fan's 12 V line |

All grounds are common: 12 V adapter negative, buck converter negative, servo ground, ESP32 ground, and fan ground. Without the common ground the fan PWM signal has no reference.

### 8.3 PWM outputs

**Servos.** The ESP32Servo library generates 50 Hz pulses of 500–2400 µs. Each servo angle is calculated from the received percentage:

```text
angle = CLOSED_DEG[i] + (OPEN_DEG[i] - CLOSED_DEG[i]) × pct / 100
```

The defaults are `CLOSED_DEG = {0,0,0,0}` and `OPEN_DEG = {90,90,90,90}`. They are calibration values: if a flap moves the wrong way, swap that zone's closed and open values. The pulse width must not drive a flap against a mechanical end stop, because the servo will buzz and draw stall current.

**Fan.** The 4-pin fan's PWM input is driven at 25 kHz with 8-bit resolution. The firmware supports both Arduino-ESP32 core generations [2][3]:

- core 3.x: `ledcAttach(pin, freq, bits)` and `ledcWrite(pin, duty)`;
- core 2.x: `ledcSetup(channel, freq, bits)`, `ledcAttachPin(pin, channel)`, and `ledcWrite(channel, duty)`.

The selection is made with `#if ESP_ARDUINO_VERSION_MAJOR >= 3`. The firmware uses no Wi-Fi, no web server, and no `String` objects; serial input is collected in a fixed 64-byte character buffer.

### 8.4 Main loop and safety behaviour

The loop is non-blocking. It never uses `delay()` or `readStringUntil()`.

| Event | Action |
|---|---|
| Serial bytes arrive | Append to the 64-byte buffer until `\n` |
| Complete line received | Parse exactly six integers; all must be 0–100 |
| Valid `V` line | Set the vent and fan targets, reset `lastRxMs`, enter NORMAL |
| Invalid line | Print `E,badline`; ignore it |
| Every 20 ms | Move each servo at most 1° and the fan at most 1 percentage point toward its target |
| Every 1 s | Print `S,<MODE>,<angA>,<angB>,<angC>,<angD>,<fanPct>` |
| No valid line for 10 s | Enter SAFE: all vents 50 %, fan 30 % |
| Valid line while in SAFE | Return to NORMAL |

At boot the firmware enters BOOT, closes all vents, sets the fan to 0 %, and starts the timeout clock. There is no separate manual mode: calibration is done by changing the constants and reflashing, or by sending a temporary percentage line during bench testing.

The status LED blinks slowly in NORMAL and quickly in SAFE. During the brief BOOT state the outputs are closed and the LED state is not safety-critical.

### 8.5 Optional relay

A relay module on GPIO 27 is declared but commented out by default. If fitted, it switches the fan's 12 V line and provides the only true off state in IDLE. It must not be used to pulse the fan for speed control; speed remains the 25 kHz PWM signal. The relay is an optional refinement, not part of the primary control loop.

### 8.6 Firmware checks

The sketch is written for the **ESP32 Dev Module** board and must compile on both Arduino-ESP32 core 2.x and 3.x. If `arduino-cli` is available, the check is:

```text
arduino-cli compile --fqbn esp32:esp32:esp32 esp32/smart_hvac/
```

If it is not available, the file is reviewed line by line for syntax, pin definitions, the core-version guard, and the non-blocking serial logic.

---

## 9. Hardware specification

### 9.1 Bill of materials

| Item | Specification | Notes |
|---|---|---|
| ESP32 | Classic ESP32 DevKit (ESP32-WROOM-32) | Powered from the laptop USB cable |
| Servos | 4 × SG90 or MG90S | One per vent flap |
| Fan | 12 V 4-pin 120 mm PC fan | PWM wire on GPIO 23 |
| 12 V adapter | 2 A minimum, 3 A preferred | Feeds fan and buck converter |
| 5 V buck converter | **3 A minimum; 5 A recommended if servos jitter** | Feeds servos only |
| Capacitor | 1000 µF, 16 V | Across the 5 V servo rail, close to the servos |
| Wiring | Jumper wires, breadboard or perfboard | Keep power and signal grounds common |
| Box | Foam board, cardboard, or similar | Sealed plenum with four outlets |
| Airflow indicators | Paper ribbons or small pinwheels | Make airflow visible in the demo |
| Camera mount | Phone holder or tripod | Fixed after zone calibration |
| Optional | Relay module | True fan cut-off on the 12 V line |

### 9.2 Power and wiring rules

1. The 12 V adapter feeds the fan and the input of the 5 V buck converter.
2. **Before connecting any servo**, set the buck output to **5.0 V** and verify it with a multimeter.
3. The 5 V output feeds the four servos only. Place the 1000 µF capacitor across this rail, physically close to the servos.
4. The ESP32 is powered from the laptop USB cable only. Never feed the servo rail into the ESP32 5 V or VIN pin.
5. Join all grounds: adapter negative, buck negative, servo ground, ESP32 GND, and fan ground.
6. Servo signals go to GPIO 18, 19, 21, 22. Fan pin 4 (PWM) goes to GPIO 23; fan pin 1 is ground, pin 2 is +12 V, pin 3 is tach (not used).
7. An SG90 can draw about **0.65 A when stalled** at 5 V, a typical figure that must be checked against the actual servo datasheet. Four servos can therefore reach about **2.6 A**. A 3 A buck converter is the minimum, not a comfortable margin; it is already close to its limit before capacitor inrush and wiring loss. If the servos jitter, the ESP32 resets, or the 5 V rail sags, move to a **5 V 5 A** supply.
8. The optional relay switches the fan's 12 V line. It is the only full cut-off; PWM alone may leave the fan spinning at its minimum speed.

### 9.3 Mechanical construction

The plenum box is the most underestimated part of the demo. It must be sealed at the fan inlet, have four outlets, and use one hinged flap per outlet moved directly by a servo horn. The flaps must close without visible gaps. Tape a paper ribbon or pinwheel at each outlet so the audience can see which vent is receiving air. A leaky box makes the vent control look ineffective even when the software is correct.

### 9.4 Camera installation

Mount the camera high enough to see the floor and full bodies, but not so steeply overhead that people appear as heads only. The whole room should be in frame, with each zone visible. Fix the camera after calibrating the zones; moving it invalidates the polygons. A phone on the demo hotspot and a fixed IP camera in a permanent installation use the same pipeline.

### 9.5 Bench bring-up order

1. ESP32 alone: flash, confirm the `S` status lines, and confirm BOOT/SAFE behaviour.
2. Fan alone: send fan percentages through a temporary `V` line.
3. One servo on the 5 V rail: test 0 % and 100 %.
4. All four servos: check for rail sag and reset; calibrate closed/open angles.
5. Serial test with typed percentage lines: confirm NORMAL, SAFE, and `E,badline`.
6. Add the camera and run the laptop pipeline.
7. Add the plenum box and flaps.
8. Run the full scenario and the power test in Section 11.

---

## 10. Software build and deliverables

### 10.1 Project structure

```text
smart-hvac/
├─ requirements.txt
├─ README.md
├─ config.py
├─ camera.py
├─ detector.py
├─ zones.py
├─ control.py
├─ serial_link.py
├─ pipeline.py
├─ server.py
├─ main.py
├─ models/
│  └─ yolo11n.pt
├─ logs/
├─ tests/
│  ├─ test_control.py
│  ├─ test_zones.py
│  └─ bus.jpg
└─ esp32/
   └─ smart_hvac/
      └─ smart_hvac.ino
```

`config.py` holds every tunable value. Nothing that affects behaviour is hard-coded in another module. The laptop program uses plain functions and small classes, type hints, short comments, and `pathlib` for file paths. There is no database, cloud service, or asynchronous framework.

### 10.2 Implementation phases

| Phase | Deliverable | Purpose |
|---|---|---|
| 0 | Environment, dependencies, weights | Reproducible setup and an offline model |
| 1 | `camera.py`, `detector.py`, baseline `main.py` | Phone or webcam in, large `PEOPLE: N` out |
| 2 | `pipeline.py`, `server.py` | Browser dashboard on the local network |
| 3 | HTTPS `/camera` and `/upload` | Phone browser as the camera, no app |
| 4 | `zones.py`, `control.py`, tests | Feet-point zones, smoothing, control equations |
| 5 | `serial_link.py`, simulator, CSV logging | Full software path with a dummy or real ESP32 |
| 6 | `esp32/smart_hvac/smart_hvac.ino` | Actuator mapping, slew limiting, 10 s failsafe |
| 7 | `README.md`, demo script | Repeatable installation and demonstration |

Phases 0–2 are demo-critical and must not depend on serial or ESP32 code. The simulator and dummy link remain usable even if the hardware is absent.

### 10.3 Operating commands

The verified entry point for the people-counting demonstration is `main.py`:

| Mode | Command |
|---|---|
| iPhone DroidCam (demo) | `python main.py --source "http://PHONE_IP:4747/video" --window` |
| USB webcam | `python main.py --source 0 --window` |
| Android IP Webcam | `python main.py --source http://PHONE_IP:8080/video --window` |
| Recorded video | `python main.py --source path/to/video.mp4 --window` |
| Single image check | `python main.py --source tests/bus.jpg` |
| Help | `python main.py --help` |

Orientation, confidence, input size and tiling defaults are in `config.py`; they can be overridden with `--rotate`, `--flip`, `--conf`, `--imgsz` and `--tiles`. In the window, `q` quits, `r` rotates by 90° and `f` cycles flips. The detector defaults that were verified for the demo are `--conf 0.25 --imgsz 640 --tiles 2 --rotate 90`.

The dashboard (`server.py`), phone-browser camera and ESP32 serial link are assembled around the same `Pipeline` and `LatestFrameReader` when the hardware rig is connected. The no-hardware counting demo above does not require them.

### 10.4 Logging

Each run writes `logs/run-YYYYmmdd-HHMMSS.csv`, one row per second:

```text
time, source, raw_total, zone_A, zone_B, zone_C, zone_D,
vents, fan, mode, fps, latency_ms, camera_ok, esp_connected
```

`latency_ms` is measured from the frame timestamp to the serial send. The file contains numbers and short state labels only. No frame, crop, image path, or video is written in live mode.

---

## 11. Testing and verification

### 11.1 Automated tests

| Test | What it checks | Pass criterion |
|---|---|---|
| `pytest -q` | All unit tests | No failures |
| Control vectors | Ten vectors in Section 5.8 | Every vent and fan value matches exactly |
| Rounding | Half-up case `1,2,0,2` | Zone A is 58 %, not 57 % |
| IDLE hold | Zero counts for less than and more than 5 s | Previous outputs held, then vents 0 / fan 0 |
| IDLE recovery | One person returns after IDLE | Normal control resumes immediately |
| Zone quadrants | One feet point in each quadrant | Correct zone in all four cases |
| Zone boundary | Box straddling a split | Assigned by its feet point |
| Outside point | Feet point outside all polygons | Counted in total, in no zone |
| Median smoother | Outlier and short window | Median, not mean; no crash on first samples |
| Serial parser | Valid, short, non-integer, out-of-range lines | Valid accepted; others produce `E` |
| Headless simulator | `python main.py --sim --port dummy` | Exit code 0, CSV rows present, no images written |

### 11.2 System tests

| Test | Method | Pass target |
|---|---|---|
| Counting accuracy | About 10 scenes in the real room, manual count compared with the system count at the same moment | At least 9 of 10 scene totals within ±1 for groups of 1–5; no zone count more than 1 out |
| Frame-to-command delay | Read `latency_ms` from the CSV over a run of at least 60 s | Median at most 500 ms; no unexplained multi-second values |
| End-to-end response | Person enters a zone; time until the vent starts to move and until it is fully open | Starts within 3 s; fully open within 5 s |
| Failsafe entry | Stop the camera or unplug the USB cable while running | SAFE within 10.0–10.5 s |
| Failsafe recovery | Restore a valid `V` line | NORMAL returns immediately; vents move to commanded values |
| Power test | Four servos moving together; measure the 5 V rail and watch for ESP32 resets | Rail at least 4.75 V; no reset; 3 A supply minimum, 5 A if jitter |
| Fan response | Command 30 %, 50 %, 84 %, 100 % | Actual fan follows the command; no stall at the low end |
| Dashboard and phone | Open the dashboard on a phone and use `/camera` on Android and iPhone | Live count and boxes visible; certificate warning can be bypassed |
| Privacy | Inspect the project directory and logs after a live run | No image or video files created; CSV contains numbers only |
| Detector speed | Measure processed FPS in the console | At least 1.0 processed frame per second with 2 × 2 tiling on the demo laptop; tiling can be disabled for about 4–5 FPS when distance accuracy is not needed |

At the time of writing, the still-image test (`tests/bus.jpg`, 4/4), the live 1–2 person tests (including a slight overlap and a far-end position) and the stream-reconnect tests pass. The ten-scene classroom accuracy sweep is scheduled for the venue, where the camera height and lighting are final.

### 11.3 Evidence and reporting

Test results are recorded in the run log and in the README. A target is not reported as met unless the command output, CSV, or measurement supports it. The control vectors are deterministic and must reproduce exactly; the camera and power tests are measured on the actual rig and include the conditions (lighting, distance, servo model, supply rating).

---

## 12. Limitations

| Limitation | Effect | Mitigation |
|---|---|---|
| Counts are not heat load | A room with ten seated people and a room with ten active people have different cooling needs; occupancy is only a proxy | Use occupancy for airflow, not as a temperature controller; add DS18B20 feedback in future work |
| People overlap | Two people close together may produce one detection box, so the total and one zone can be undercounted | Tiled detection and the merge rules keep two slightly overlapping people separate; heavy occlusion can still hide one. Mount the camera high and avoid fully hidden people |
| Zone edges are fuzzy | A person standing on a boundary can flip between zones as the feet point moves | Calibrate `zones.json` to the room, use the median filter, and avoid standing on the split during the demo |
| Lighting varies | Low light, backlight, and changing daylight reduce detection confidence | Lock exposure, use even lighting, test at the venue, and keep the confidence threshold at 0.25 |
| The camera must be mounted high | A low or steep view causes occlusion, heads-only detections, and distorted zones | Use a high corner or wall mount with a moderate downward angle; fix it after calibration |
| Phone camera suspends | The iOS stream stops when the screen locks or DroidCam is backgrounded | Auto-Lock Never, Low Power Mode off, charger connected, DroidCam in the foreground; the reader reconnects automatically if it does drop |
| No tracking across frames | A detection can flicker or double-count briefly | Median smoothing suppresses single-frame errors; tracking is left as future work |
| Single camera view | People hidden behind furniture or columns are invisible | Choose a view that covers all four zones; state the blind spots in the demo |

These limitations do not invalidate the control demonstration, but they define what the occupancy number can and cannot be used for.

---

## 13. Licence and privacy

### 13.1 Licence

The vision component uses Ultralytics YOLO, which is released under the **GNU Affero General Public License v3.0 (AGPL-3.0)** [4]. Use for academic coursework and a local demonstration is compatible with the licence. The AGPL also imposes source-disclosure obligations if a modified version is offered as a network service or redistributed; that is outside the scope of this project. A commercial Ultralytics licence would be required for a closed-source product. The software is provided without warranty.

### 13.2 Privacy

- Live camera frames, browser uploads, and annotated JPEGs exist only in memory.
- The program never writes a frame, crop, or video to disk in live mode.
- The CSV log contains counts, percentages, mode labels, timings, and connection state. It contains no images and no personal identifiers.
- The system counts bounding boxes; it does not perform face recognition or identify individuals.
- The dashboard is served on the local network. There is no cloud service and no external upload.
- The phone-browser camera uses a self-signed certificate, so the browser shows a warning. Traffic stays on the local network.
- People in the room should be informed that a camera is being used for occupancy counting, even though no images are stored.

The last point is an ethical requirement as well as a privacy one: the absence of stored images reduces risk, but it does not remove the need for consent and a visible camera.

---

## 14. Future work

1. **DS18B20 temperature feedback.** Add one sensor per zone and use the measured temperature error to bias the vent opening. Occupancy would remain the feed-forward signal, while temperature would close the control loop.
2. **CO₂ sensing.** A CO₂ sensor per zone would provide a direct ventilation-demand signal. This is more closely related to air quality than occupancy alone and would allow the fan to respond to exhaled air rather than only to people counts.
3. **ESP32-CAM edge counting.** A small camera module could perform counting at the edge, removing the laptop from the runtime path. This would improve portability but would require a much smaller model and careful validation of accuracy, heat, and power.

These are extensions, not requirements for the current build.

---

## 15. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Camera or Wi-Fi fails on demo day | Use the phone hotspot, USB webcam, recorded video, or simulator fallback |
| YOLO misses seated or occluded people | Mount the camera at a moderate height, test with real seating, and use `yolo11s.pt` if the laptop allows |
| Toys or dolls are not detected as people | Use real people or full-body standees in the demonstration |
| Servo current resets the ESP32 or browns out the rail | Separate 5 V supply rated at least 3 A, 5 A if jitter, 1000 µF capacitor, common ground, ESP32 powered from USB |
| Leaky flaps make the airflow demonstration unconvincing | Build and seal the plenum early; test each flap against its outlet |
| The fan keeps spinning at minimum PWM | Idle mode: vents closed, fan at minimum PWM. A relay on the 12 V line is the optional full cut-off. |
| Arduino core or servo library mismatch | Use a compatible ESP32Servo version and the `ESP_ARDUINO_VERSION_MAJOR` guard for the fan LEDC calls |
| Serial noise or a partial line | Strict six-field parser, range checks, `E,badline`, and the 10 s watchdog |
| Laptop stalls or the camera freezes while the program still runs | Send only while the newest frame is under 3 s old; otherwise the ESP32 reaches SAFE after 10 s |
| Phone browser refuses the camera or cannot reach the laptop | Use HTTPS on port 8443, accept the self-signed certificate, and allow the app on Windows Private networks |
| Zone calibration drifts after mounting | Fix the camera after calibration and keep `zones.json` under version control |
| A running fan against closed vents builds pressure | Keep the 15 % minimum while the room is occupied; the value is configurable |

---

## 16. Demo script

### 16.1 People-counting demonstration (no hardware, verified)

**Target duration: 60–90 seconds.** This is the path used when the ESP32 rig is not present.

1. **Phone ready.** DroidCam is open in the foreground, Auto-Lock is Never, the charger is connected, and the laptop is on the phone's hotspot.
2. **Start.** Run `python main.py --source "http://PHONE_IP:4747/video" --window`. Wait for `Camera: connected`.
3. **One person enters.** The window shows one numbered box and `PEOPLE: 1`.
4. **Second person enters.** `PEOPLE: 2`.
5. **One steps slightly behind the other.** The count stays at 2; both keep a box. Say: *"Tiling finds the person at the back, and the merge rules keep two overlapping people separate."*
6. **One walks to the far end.** The far person is still boxed and counted.
7. **Both leave.** The count falls to 0 after the median window clears.
8. **Fallback.** If the phone fails, run `python main.py --source tests/bus.jpg`; it prints `People: 4` and writes the annotated image.

### 16.2 Full system with ESP32

**Target duration: about two minutes.**

1. **Power and link.** Start the laptop program, then power the ESP32. The ESP32 shows BOOT with vents closed and fan 0 %, then NORMAL after the first valid command. The dashboard shows `ESP32: connected`.
2. **Empty room.** Wait for the 5 s hold. The system enters IDLE. Say: “Idle mode: vents closed, fan at minimum PWM. A relay on the 12 V line is the optional full cut-off.”
3. **Three people in zone B.** Vent B opens to 100 %, A, C, and D stay at 15 %, and the fan rises to 44 %. Point out the feet dots and the per-zone count.
4. **Five more people in zone D.** The total is 8. D is 100 %, B falls to 66 %, and the fan rises to 84 %.
5. **Two more people in zone A.** The total reaches 10. A is 49 %, B 66 %, C 15 %, D 100 %, and the fan is capped at 100 %.
6. **People leave.** Show the slow ramp-down. After the 5 s empty hold, the system returns to IDLE.
7. **Failsafe.** Stop the camera or unplug the USB cable. After about 10 s the ESP32 enters SAFE: all vents 50 %, fan 30 %. Restore the link and show the return to NORMAL.
8. **Optional fallback.** Open `/camera` on the phone and show the same count and boxes on the phone. Then open the simulator and demonstrate the logic with no camera or hardware.

**Before the demo:** open DroidCam, set Auto-Lock to Never, disable Low Power Mode, connect the charger, and confirm the phone hotspot. For the hardware path, calibrate the zones and each flap, allow the firewall prompt for private networks, and bring a tripod. Keep `tests/bus.jpg` as the no-camera fallback, plus a recorded video and a USB webcam as backups. Stand 2–3 m back so full bodies are in frame. The one-page checklist is in `DEMO_RUNBOOK.md`.

---

## 17. Conclusion

This report has defined a complete, buildable system for occupancy-aware zone ventilation. The design separates the vision workload from the real-time actuator path: the laptop detects people, assigns them to zones, smooths the counts, and applies a small set of explicit equations; the ESP32 converts percentages into servo angles and fan PWM, limits motion, and owns the 10 s failsafe. The empty-room state, the 15 % minimum vent opening, the half-up rounding rule, the serial contract, and the behaviour on camera or link failure are all specified rather than left to implementation.

The design also acknowledges its limits. Occupancy is not heat load, overlapping people can be undercounted, zone boundaries are sensitive to camera placement, and lighting affects detection. The test plan addresses these limits with repeatable unit tests and measured scene, latency, failsafe, and power tests. The result is a system that can be demonstrated safely with no hardware, then commissioned on the real rig without changing the control logic.

---

## References

[1] Ultralytics. *YOLO11 documentation.* https://docs.ultralytics.com/models/yolo11/ (accessed 2 November 2026).

[2] Espressif Systems. *ESP32 Series Datasheet.* https://www.espressif.com/en/products/socs/esp32 (accessed 2 November 2026).

[3] Espressif Systems. *Arduino-ESP32 documentation.* https://docs.espressif.com/projects/arduino-esp32/en/latest/ (accessed 2 November 2026).

[4] Free Software Foundation. *GNU Affero General Public License, version 3.* https://www.gnu.org/licenses/agpl-3.0.html (accessed 2 November 2026).

[5] OpenCV. *Image Processing – pointPolygonTest.* https://docs.opencv.org/4.x/d6/d6e/group__imgproc__shape.html (accessed 2 November 2026).

[6] Jocher, G., & Qiu, J. (2024). *Ultralytics YOLO11* (Version 11.0.0) [Computer software]. https://github.com/ultralytics/ultralytics. AGPL-3.0. Tested with the `ultralytics` Python package version 8.4.190.

[7] Redmon, J., Divvala, S., Girshick, R., & Farhadi, A. (2016). You Only Look Once: Unified, Real-Time Object Detection. *Proceedings of the IEEE Conference on Computer Vision and Pattern Recognition (CVPR)*, 779–788. https://doi.org/10.1109/CVPR.2016.91. arXiv:1506.02640.

[8] Akyon, F. C., Altinuc, S. O., & Temizel, A. (2022). Slicing Aided Hyper Inference and Fine-tuning for Small Object Detection. *2022 IEEE International Conference on Image Processing (ICIP)*. https://doi.org/10.1109/ICIP46576.2022.9897990. arXiv:2202.06934.

[9] Neubeck, A., & Van Gool, L. (2006). Efficient Non-Maximum Suppression. *18th International Conference on Pattern Recognition (ICPR'06)*, 850–855. https://doi.org/10.1109/ICPR.2006.479.

[10] Jaccard, P. (1901). Étude comparative de la distribution florale dans une portion des Alpes et du Jura. *Bulletin de la Société Vaudoise des Sciences Naturelles*, 37, 547–579.

[11] Tukey, J. W. (1977). *Exploratory Data Analysis.* Addison-Wesley.

[12] Astola, J., & Kuosmanen, P. (1997). *Fundamentals of Nonlinear Digital Filtering.* CRC Press.

[13] Anand, P., Cheong, D., & Sekhar, C. (2022). A review of occupancy-based building energy and IEQ controls and its future post-COVID. *Science of the Total Environment*, 804, 150249. https://doi.org/10.1016/j.scitotenv.2021.150249.

[14] OpenCV. *cv::VideoCapture Class Reference.* https://docs.opencv.org/4.x/d8/dfe/classcv_1_1VideoCapture.html (accessed 2 November 2026).

[15] Python Software Foundation. *threading – Thread-based parallelism.* https://docs.python.org/3/library/threading.html (accessed 2 November 2026).

[16] Python Software Foundation. *statistics.median.* https://docs.python.org/3/library/statistics.html#statistics.median (accessed 2 November 2026).

[17] Python Software Foundation. *math.floor.* https://docs.python.org/3/library/math.html#math.floor (accessed 2 November 2026).

[18] Pallets Projects. *Flask documentation.* https://flask.palletsprojects.com/ (accessed 2 November 2026).

[19] PySerial. *pySerial documentation.* https://pyserial.readthedocs.io/ (accessed 2 November 2026).

[20] Python Cryptographic Authority. *cryptography documentation.* https://cryptography.io/ (accessed 2 November 2026).

[21] pytest. *pytest documentation.* https://docs.pytest.org/ (accessed 2 November 2026).

[22] Ultralytics. *bus.jpg sample image.* https://ultralytics.com/images/bus.jpg (accessed 2 November 2026). AGPL-3.0.

---

## Glossary

**AGPL-3.0:** GNU Affero General Public License version 3, the licence of Ultralytics YOLO.

**Feet point:** the bottom-centre of a person's detection box, used as a proxy for where the person stands.

**HVAC:** heating, ventilation, and air conditioning.

**IDLE:** Idle mode: vents closed, fan at minimum PWM. A relay on the 12 V line is the optional full cut-off.

**Median filter:** a smoother that returns the middle value of the recent samples, so a single outlier does not change the result.

**Plenum:** the sealed box that distributes the fan's air to the four vents.

**PWM:** pulse-width modulation, used to set fan speed and servo position.

**SAFE:** the ESP32 state entered after 10 s without a valid command: all vents 50 %, fan 30 %.

**Slew limiting:** limiting how fast an output may change, to protect the servo and avoid sudden noise.

**Watchdog:** a timer that triggers a safe state when expected data stops arriving.

**Zone:** one of the four regions A–D covering the camera view.

