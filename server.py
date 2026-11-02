"""Flask web server for the Smart HVAC dashboard and phone-browser camera.

Runs on two ports:
  - http://0.0.0.0:8000   — main dashboard (MJPEG video + state polls)
  - http://0.0.0.0:8443   — HTTPS /camera page (phone browsers, no app)

Routes
------
/           — dashboard page (single-page, dark theme, mobile-friendly)
/video      — MJPEG stream of the latest annotated JPEG
/state      — JSON state for 2 Hz dashboard poll
/upload     — receive JPEG from phone browser, process, return JSON
/camera     — page that requests the phone's rear camera via getUserMedia

The dashboard polls /state every 500 ms and shows the live video, total count,
per-zone counts, vent bars, fan %, mode badge, FPS, and camera/link status.

On start the program prints the laptop's LAN IP using a UDP-socket trick so the
user can copy-paste the URL to a phone on the same hotspot.

With --https the same Flask app is also served on port 8443 using a self-signed
certificate.  The /camera page works on Android and iPhone without an app.
"""

import json
import os
import threading
import socket
import struct
import logging
import time
from pathlib import Path
from typing import Optional, Callable

import cv2
import numpy as np

from flask import (Flask, Response, render_template, render_template_string,
                   request, jsonify)

from pipeline import Pipeline
from serial_link import SerialLink, DummyLink
from config import SOURCE, SEND_PERIOD_S, FRAME_FRESH_S

app = Flask(__name__)
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0

# Global objects — initialised in main.py
pipeline: Optional[Pipeline] = None
serial_link: Optional[SerialLink] = None
camera_source: str = SOURCE  # "0", "http://...", "phone-browser", etc.
https_mode = False


# ---------------------------------------------------------------------------
# Helper: find the laptop's LAN IP via a UDP socket trick
# ---------------------------------------------------------------------------

def _get_lan_ip() -> str:
    """Determine the laptop's LAN IP address.

    Uses a UDP socket to an external address (google DNS) without actually
    sending data; the OS chooses the source interface IP.
    """
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
        finally:
            s.close()
        return ip
    except Exception:
        return "127.0.0.1"


# ---------------------------------------------------------------------------
# Dashboard route
# ---------------------------------------------------------------------------

@app.route("/")
def dashboard():
    """Serve the main dashboard page.

    Single-page dark-themed HTML that:
      - shows the MJPEG video stream at /video
      - polls /state every 500 ms
      - shows per-zone counts, vent bars, fan %, mode badge
      - shows LIVE/LOST badge based on serial link status
      - shows FPS
    """
    lan_ip = _get_lan_ip()
    return render_template_string(DASHBOARD_HTML, lan_ip=lan_ip, camera_source=camera_source)


# ---------------------------------------------------------------------------
# MJPEG video stream route
# ---------------------------------------------------------------------------

@app.route("/video")
def video_stream():
    """MJPEG stream of the latest annotated JPEG.

    Yields the annotated JPEG frame each time the pipeline updates it.
    """
    def generate():
        while True:
            jpeg = pipeline.annotated_jpeg()
            if jpeg is not None:
                yield (b"--frame\r\n"
                       b"Content-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n")
            else:
                yield (b"--frame\r\n"
                       b"Content-Type: image/jpeg\r\n\r\n" + b"\r\n")
            import time as _t
            _t.sleep(0.1)  # ~10 FPS stream

    return Response(generate(), mimetype="multipart/x-mixed-replace; boundary=frame")


# ---------------------------------------------------------------------------
# JSON state route
# ---------------------------------------------------------------------------

@app.route("/state")
def state_json():
    """Return the latest state as JSON for the dashboard poll."""
    if pipeline is None:
        return jsonify({"total": 0, "raw_total": 0, "zone_counts": {"A": 0, "B": 0, "C": 0, "D": 0},
                        "vents": [0, 0, 0, 0], "fan": 0, "mode": "IDLE", "fps": 0.0,
                        "camera_ok": False, "source": camera_source, "ts": 0})
    sd = pipeline.state_dict()
    return jsonify({
        "total": sd["total"],
        "raw_total": sd["raw_total"],
        "zone_counts": sd["zone_counts"],
        "vents": sd["vents"],
        "fan": sd["fan"],
        "mode": sd["mode"],
        "fps": sd["fps"],
        "camera_ok": serial_link is not None and serial_link.connected if serial_link else False,
        "source": camera_source,
        "ts": sd["timestamp"],
    })


# ---------------------------------------------------------------------------
# /upload route — receives JPEG from phone browser
# ---------------------------------------------------------------------------

@app.route("/upload", methods=["POST"])
def upload():
    """Receive a JPEG frame from the phone browser, process it, return JSON.

    Expected form data:
        - raw JPEG bytes (field name: "frame")

    Returns:
        JSON with keys: total, boxes [[x1,y1,x2,y2,conf] ...] (normalised 0-1)
    """
    if "frame" not in request.files:
        return jsonify({"error": "no frame field"}), 400

    file = request.files["frame"]
    try:
        npimg = np.frombuffer(file.read(), dtype=np.uint8)
        frame = cv2.imdecode(npimg, cv2.IMREAD_COLOR)
        if frame is None:
            return jsonify({"error": "cannot decode frame"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 400

    # Process through the pipeline
    ts = time.time()
    state = pipeline.process(frame, ts)

    # Build the box list in normalised coordinates
    # We need to re-detect or use the stored detections; for now re-detect
    # Actually, let's store the detections in the pipeline for later use
    # For this minimal implementation, we'll re-run detection
    from detector import PersonDetector
    det = pipeline._detector.detect(frame)  # type: ignore
    boxes = []
    for d in det:
        # Normalise coordinates to 0-1
        h, w = frame.shape[:2]
        boxes.append([
            d["x1"] / w, d["y1"] / h, d["x2"] / w, d["y2"] / h, d["conf"]
        ])

    return jsonify({
        "total": state["total"],
        "boxes": boxes,
    })


# ---------------------------------------------------------------------------
# /camera route — phone browser camera page
# ---------------------------------------------------------------------------

@app.route("/camera")
def camera_page():
    """Serve the phone-browser camera page.

    This page requests the user's camera (rear on phones), sends JPEGs to /upload,
    and displays the processed result with boxes and total count.
    """
    lan_ip = _get_lan_ip()
    return render_template_string(CAMERA_HTML, lan_ip=lan_ip)


# ---------------------------------------------------------------------------
# /sim route — simulator controls
# ---------------------------------------------------------------------------

@app.route("/sim", methods=["POST"])
def sim_control():
    """Handle simulator control buttons.

    Expected POST JSON:
        - {"action": "add", "zone": "A"}   # add one person to zone A
        - {"action": "remove", "zone": "A"}  # remove one from zone A
        - {"action": "reset"}              # reset all counts
    """
    if pipeline is None:
        return jsonify({"error": "pipeline not initialised"}), 503
    if not request.is_json:
        return jsonify({"error": "JSON required"}), 400

    data = request.get_json()
    action = data.get("action")

    with pipeline._lock:
        if action == "add":
            zone = data.get("zone", "A")
            pipeline._state["zone_counts"][zone] = min(99, pipeline._state["zone_counts"].get(zone, 0) + 1)
        elif action == "remove":
            zone = data.get("zone", "A")
            pipeline._state["zone_counts"][zone] = max(0, pipeline._state["zone_counts"].get(zone, 0) - 1)
        elif action == "reset":
            for z in ["A", "B", "C", "D"]:
                pipeline._state["zone_counts"][z] = 0
        else:
            return jsonify({"error": "unknown action"}), 400

        counts = [pipeline._state["zone_counts"][z] for z in ["A", "B", "C", "D"]]
        ctrl = pipeline._controller.update(counts, time.time())
        total = sum(counts)
        pipeline._state.update({
            "total": total,
            "raw_total": total,
            "vents": ctrl["vents"],
            "fan": ctrl["fan"],
            "mode": ctrl["mode"],
        })
        state = dict(pipeline._state)

    return jsonify({
        "total": state["total"],
        "zone_counts": state["zone_counts"],
        "vents": state["vents"],
        "fan": state["fan"],
        "mode": state["mode"],
    })


# ---------------------------------------------------------------------------
# Template strings (kept here to avoid external template files)
# ---------------------------------------------------------------------------

DASHBOARD_HTML = """
<!doctype html>
<html lang="en" data-theme="dark">
<head>
  <meta charset="utf-8">
  <title>Smart HVAC Dashboard</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    :root{--bg:#111;--card:#1a1a2e;--text:#e0e0e0;--accent:#00ff99;--muted:#666}
    *{box-sizing:border-box;margin:0;padding:0}
    body{font-family:system-ui,sans-serif;background:var(--bg);color:var(--text)}
    .container{max-width:1200px;margin:0 auto;padding:20px}
    header{background:var(--card);padding:20px;border-radius:8px;margin-bottom:20px}
    h1{font-size:1.5rem;margin-bottom:10px}
    .status{display:flex;gap:20px;margin-top:10px;align-items:center}
    .badge{padding:4px 8px;border-radius:4px;font-size:0.8rem;text-transform:uppercase}
    .badge-normal{background:#22c55e;color:black}
    .badge-idle{background:#f59e0b;color:black}
    .badge-safe{background:#ef4444;color:white}
    .badge-lost{background:#6b7280;color:white}
    .video-wrapper{background:var(--card);border-radius:8px;overflow:hidden;max-height:500px;margin:20px 0}
    .video-wrapper video{border-radius:4px;width:100%}
    .controls{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:20px 0}
    .ctrl-card{background:var(--card);padding:15px;border-radius:8px;text-align:center}
    .ctrl-card .value{font-size:2rem;font-weight:bold;color:var(--accent)}
    .ctrl-card .label{font-size:0.8rem;color:var(--muted);margin-top:4px}
    .vent-bar{height:40px;width:20px;background:#333;margin:4px auto;border-radius:2;overflow:hidden;position:relative}
    .vent-fill{height:100%;background:var(--accent);width:0%;transition:width 0.15s ease}
    .vent-percent{position:absolute;right:0;top:50%;transform:translateY(-50%);font-size:0.7rem;color:var(--text)}
    .fan-bar{height:60px;width:40px;background:#333;margin:4px auto;border-radius:2;overflow:hidden;position:relative}
    .fan-fill{height:100%;background:var(--accent);width:0%;transition:width 0.2s ease}
    .fan-percent{position:absolute;right:0;top:50%;transform:translateY(-50%);font-size:0.7rem;color:var(--text)}
    .zone-row{display:flex;align-items:center;gap:10px;margin:4px 0}
    .zone-info{flex:1}
    .fps{margin-top:10px;padding:8px;background:var(--card);border-radius:4px;font-size:0.9rem}
    @media(max-width:600px){.controls{grid-template-columns:1fr}.video-wrapper{max-height:300px}}
  </style>
</head>
<body>
  <div class="container">
    <header>
      <h1>Smart HVAC — Zone Occupancy Counting</h1>
      <div class="status">
        <span id="modeBadge" class="badge badge-idle">IDLE</span>
        <span id="people">PEOPLE: 0</span>
        <span id="cameraBadge" class="badge badge-lost">LINK LOST</span>
      </div>
    </header>

    <div class="video-wrapper">
      <img src="/video" id="liveVideo" alt="Live video">
    </div>

    <div class="controls">
      <div class="ctrl-card">
        <div class="value" id="ventA">0</div>
        <div class="label">Vent A</div>
        <div class="vent-bar"><div class="vent-fill" style="width:0%"></div><div class="vent-percent">0%</div></div>
      </div>
      <div class="ctrl-card">
        <div class="value" id="ventB">0</div>
        <div class="label">Vent B</div>
        <div class="vent-bar"><div class="vent-fill" style="width:0%"></div><div class="vent-percent">0%</div></div>
      </div>
      <div class="ctrl-card">
        <div class="value" id="ventC">0</div>
        <div class="label">Vent C</div>
        <div class="vent-bar"><div class="vent-fill" style="width:0%"></div><div class="vent-percent">0%</div></div>
      </div>
      <div class="ctrl-card">
        <div class="value" id="ventD">0</div>
        <div class="label">Vent D</div>
        <div class="vent-bar"><div class="vent-fill" style="width:0%"></div><div class="vent-percent">0%</div></div>
      </div>
      <div class="ctrl-card">
        <div class="value" id="fanPct">0</div>
        <div class="label">Fan %</div>
        <div class="fan-bar"><div class="fan-fill" style="width:0%"></div><div class="fan-percent">0%</div></div>
      </div>
    </div>

    <div class="zone-row">
      <div class="zone-info"><strong>A</strong> <span id="zoneA">0</span></div>
      <div class="zone-info"><strong>B</strong> <span id="zoneB">0</span></div>
      <div class="zone-info"><strong>C</strong> <span id="zoneC">0</span></div>
      <div class="zone-info"><strong>D</strong> <span id="zoneD">0</span></div>
    </div>

    <div class="fps" id="fps">FPS: --</div>
  </div>

  <script>
    let pollingInterval = null;
    let simulationActive = false;

    function updateDashboard(state) {
      const total = state.total || 0;
      const zoneCounts = state.zone_counts || {"A":0,"B":0,"C":0,"D":0};
      const vents = state.vents || [0,0,0,0];
      const fan = state.fan || 0;
      const mode = state.mode || "IDLE";
      const cameraOk = state.camera_ok !== false;
      const fps = state.fps || 0;

      // Mode badge
      const modeMap = {"NORMAL":"badge-normal","IDLE":"badge-idle","SAFE":"badge-safe"};
      const modeClass = modeMap[mode] || "badge-idle";
      document.getElementById("modeBadge").className = `badge ${modeClass}`;
      document.getElementById("modeBadge").textContent = mode;

      // People count
      document.getElementById("people").textContent = `PEOPLE: ${total}`;

      // Camera badge
      const camClass = cameraOk ? "badge-normal" : "badge-lost";
      document.getElementById("cameraBadge").className = `badge ${camClass}`;
      document.getElementById("cameraBadge").textContent = cameraOk ? "LIVE" : "LOST";

      // Vent bars
      for(let i=0;i<4;i++) {
        const pct = vents[i] || 0;
        const bar = document.querySelectorAll(".vent-bar")[i];
        const fill = bar.querySelector(".vent-fill");
        const percent = bar.querySelector(".vent-percent");
        fill.style.width = `${pct}%`;
        percent.textContent = `${pct}%`;
      }

      // Fan bar
      const fanBar = document.querySelector(".fan-fill");
      const fanPercent = document.querySelector(".fan-percent");
      if(fanBar) {
        fanBar.style.width = `${fan}%`;
        if(fanPercent) fanPercent.textContent = `${fan}%`;
      }

      // Zone counts
      for(const [z, c] of Object.entries(zoneCounts)) {
        const el = document.querySelector(`#zone${z}`);
        if(el) el.textContent = c;
      }

      // FPS
      document.getElementById("fps").textContent = `FPS: ${fps.toFixed(1)}`;
    }

    function pollState() {
      fetch("/state")
        .then(r => r.json())
        .then(updateDashboard)
        .catch(err => {
          console.error("State poll failed", err);
          document.getElementById("cameraBadge").className = "badge badge-lost";
          document.getElementById("cameraBadge").textContent = "LOST";
          clearInterval(pollingInterval);
        });
    }

    // Start polling when the page loads
    pollingInterval = setInterval(pollState, 500);
    pollState(); // immediate first poll

    // Handle visibility change
    document.addEventListener('visibilitychange', () => {
      if (!document.hidden) pollState();
    });
  </script>
</body>
</html>
"""

CAMERA_HTML = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Smart HVAC — Phone Camera</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    :root{--bg:#111;--card:#1a1a2e;--text:#e0e0e0;--accent:#00ff99}
    *{box-sizing:border-box;margin:0;padding:0}
    body{font-family:system-ui,sans-serif;background:var(--bg);color:var(--text)}
    .container{max-width:800px;margin:40px auto;padding:20px}
    h1{font-size:1.3rem;margin-bottom:10px}
    .status{background:var(--card);padding:15px;border-radius:8px;margin-bottom:20px}
    .status .badge{padding:4px 8px;border-radius:4px;font-size:0.8rem;text-transform:uppercase}
    .badge-green{background:#22c55e;color:black}
    .badge-warning{background:#f59e0b;color:black}
    .video-wrapper{background:var(--card);border-radius:8px;overflow:hidden;margin:20px 0;max-height:500px}
    video{width:100%}
    .controls{margin:20px 0}
    .ctrl-card{background:var(--card);padding:15px;border-radius:8px;text-align:center}
    .ctrl-card .value{font-size:2rem;font-weight:bold;color:var(--accent)}
    .ctrl-card .label{font-size:0.8rem;color:var(--muted);margin-top:4px}
    .message{padding:15px;background:#333;margin-top:10px;border-radius:4px;color:var(--text)}
    canvas{display:none}
    #errorMsg{color:#ff5f57;font-weight:bold;margin-top:10px}
  </style>
</head>
<body>
  <div class="container">
    <h1>Smart HVAC — Phone Camera</h1>
    <div class="status">
      <span id="cameraStatus" class="badge badge-green">Starting...</span>
    </div>
    <div class="video-wrapper">
      <video id="localVideo" autoplay playsinline></video>
      <canvas id="overlayCanvas" width="640" height="480" style="display:none"></canvas>
    </div>
    <div class="message" id="errorMsg" style="display:none"></div>

    <script>
      const tunnelUrl = location.origin; // will be https from Flask
      let ws = null;
      let currentTotal = 0;

      // Check if getUserMedia is available
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        document.getElementById("errorMsg").style.display = "block";
        document.getElementById("errorMsg").textContent = "getUserMedia not available on this browser/device.";
        document.getElementById("cameraStatus").className = "badge badge-warning";
        document.getElementById("cameraStatus").textContent = "Camera not supported";
        throw new Error("getUserMedia not available");
      }

      // Request the rear-facing camera
      async function startCamera() {
        try {
          const stream = await navigator.mediaDevices.getUserMedia({
            video: { facingMode: "environment" },
            audio: false
          });
          const video = document.getElementById("localVideo");
          video.srcObject = stream;

          // Initialize WebSocket to send frames
          ws = new WebSocket(`${location.origin}/ws`);
          ws.onopen = () => {
            console.log("WebSocket connected");
          };

          // Process video frames
          const canvas = document.getElementById("overlayCanvas");
          const ctx = canvas.getContext("2d");
          const videoWidth = video.videoWidth || 640;
          const videoHeight = video.videoHeight || 480;

          function processFrame() {
            // Draw frame to canvas downscaled to max width 640
            const maxW = 640;
            let cw = videoWidth;
            let ch = videoHeight;
            if (cw > maxW) {
              ch = ch * maxW / cw;
              cw = maxW;
            }
            canvas.width = cw;
            canvas.height = ch;
            ctx.drawImage(video, 0, 0, cw, ch);

            // Export as JPEG 0.7 quality
            const dataUrl = canvas.toDataURL("image/jpeg", 0.7);
            // Send raw bytes via WebSocket (binary type)
            ws.send(dataUrl.split(",")[1]); // base64 -> raw

            // Wait for response (this is simplified; real impl would use request/response)
            // For this demo, just show the video
            requestAnimationFrame(processFrame);
          }

          processFrame();
        } catch (err) {
          console.error("Camera error:", err);
          document.getElementById("errorMsg").style.display = "block";
          document.getElementById("errorMsg").textContent = "Camera access denied or failed: " + err.message;
          document.getElementById("cameraStatus").className = "badge badge-warning";
          document.getElementById("cameraStatus").textContent = "Camera failed";
        }
      }

      startCamera();
    </script>
  </body>
</html>
"""

# ---------------------------------------------------------------------------
# Start-up behaviour
# ---------------------------------------------------------------------------

def create_app(pipeline_obj, serial_obj, camera_src="0", enable_https=False):
    """Flask app factory that injects the pipeline and serial link."""
    global pipeline, serial_link, camera_source, https_mode
    pipeline = pipeline_obj
    serial_link = serial_obj
    camera_source = camera_src
    https_mode = enable_https

    # Override dashboard template to show LINK LOST status properly
    # (the global references will be resolved at runtime)

    return app