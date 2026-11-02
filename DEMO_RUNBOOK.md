# Demo runbook - people counter

This runbook uses the verified camera-counting path (`main.py`). No ESP32,
dashboard, or internet connection is needed once the model weights are present.

---

## 1. Five minutes before the demo

On the **phone**:

1. Open **DroidCam** and leave it in the foreground.
2. Set **Settings -> Display & Brightness -> Auto-Lock -> Never**.
3. Turn **Low Power Mode** off.
4. Connect the charger.
5. Note the IP address shown in DroidCam. The examples below use
   `192.168.1.42`; replace it with your phone's address.

On the **laptop**:

1. Join the phone's hotspot.
2. Open PowerShell in the repository root.
3. Set the phone address for this session:

```powershell
$PHONE_IP = "192.168.1.42"
```

4. Check that the phone is reachable:

```powershell
.\.venv\Scripts\python.exe -c "import socket; s=socket.socket(); s.settimeout(2); print('phone:', 'OK' if s.connect_ex(('$PHONE_IP',4747))==0 else 'ASLEEP'); s.close()"
```

If it says `ASLEEP`, wake the phone and bring DroidCam to the foreground.

---

## 2. Start the demo

```powershell
.\.venv\Scripts\python.exe main.py --source "http://$PHONE_IP:4747/video" --window
```

Expected first lines:

```text
Source: http://192.168.1.42:4747/video | conf: 0.25 | imgsz: 640 | tiles: 2 | flip: none | rotate: 90
Camera: waiting for video...
Camera: connected
People: 1
```

If the room is still empty, the first count may be `0`; that is normal.

### Window legend

| Element | Meaning |
|---|---|
| Green numbered boxes `#1, #2, ...` | One box per counted person |
| `PEOPLE: N` | Stabilised count (median of the last 5 frames) |
| `raw N` | Count on the current frame |
| `camera LIVE` | New frames are arriving |
| `camera LOST` | Stream dropped; the reader is reconnecting automatically |

### Keys

| Key | Action |
|---|---|
| `q` | Quit |
| `r` | Rotate the image 90 degrees (use if the view is sideways or upside down) |
| `f` | Cycle flips (use only if the image is mirrored) |

---

## 3. The 60-second demo script

1. **One person walks in** -> `PEOPLE: 1`.
2. **Second person walks in** -> `PEOPLE: 2`.
3. **One steps slightly behind the other** -> still `PEOPLE: 2`; both keep a box.
4. **One walks to the far end / back of the room** -> still counted
   (`PEOPLE: 2` while both are visible).
5. **Both leave** -> after a few frames, `PEOPLE: 0`.

Say: *"Each person is detected on the full frame and on four overlapping tiles,
so someone at the back of the room is still large enough for the model.
Duplicate boxes from the tile overlaps are merged, but two people who overlap
each other are kept separate."*

Optional, only if it is already working: cover the phone camera briefly, show
`camera LOST`, uncover it, and show it reconnect in about 1-3 seconds. Do not do
this if the phone has been unstable.

---

## 4. If something goes wrong

| Symptom | Fix |
|---|---|
| `Camera: waiting for video...` and nothing else | Wake the phone, reopen DroidCam, keep it foreground |
| Phone IP changed | Read the new IP in DroidCam and restart with `--source "http://NEW_IP:4747/video"` |
| View is sideways / upside down | Press `r` until upright; the app prints the new rotation |
| View is mirrored | Press `f` until correct |
| Count updates slowly | Normal on a laptop CPU: about 1-1.5 processed frames per second. Close other heavy apps |
| Stream keeps dropping | Phone Wi-Fi power save; keep the screen on and the charger connected |
| Total failure | Run the still-image fallback (below); it always gives `People: 4` |

### Find the phone if the IP changed

Set the subnet prefix used by your hotspot, then scan ports 4747:

```powershell
$subnet = "192.168.1."
.\.venv\Scripts\python.exe -c "import socket, concurrent.futures
def p(ip):
    s=socket.socket(); s.settimeout(0.18)
    try: return ip if s.connect_ex((ip,4747))==0 else None
    finally: s.close()
with concurrent.futures.ThreadPoolExecutor(max_workers=96) as ex:
    print([r for r in ex.map(p, [f'$subnet{i}' for i in range(1,255)]) if r])"
```

### Still-image fallback (no phone, no camera)

```powershell
.\.venv\Scripts\python.exe main.py --source tests\bus.jpg
```

Expected:

```text
People: 4
Saved out_bus.jpg
```

Open `out_bus.jpg` to show the four numbered boxes.

---

## 5. Final pre-demo check (2 minutes)

- [ ] Phone: Auto-Lock **Never**, Low Power Mode **off**, charger **connected**
- [ ] DroidCam **open and foreground**
- [ ] Laptop on the phone hotspot
- [ ] App starts and prints `Camera: connected`
- [ ] One person -> 1, two people -> 2
- [ ] Slight overlap still shows 2
- [ ] `q` quits cleanly

Do not change `config.py` now. The verified values are:

```text
CONF = 0.25
IOU = 0.70
IMGSZ = 640
DETECT_TILES = 2
TILE_OVERLAP = 0.25
CAMERA_ROTATE = 90
```
