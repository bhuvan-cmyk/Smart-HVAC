# ESP32 firmware

This folder is reserved for the ESP32 actuator firmware.

## Status in this public snapshot

The firmware **sketch is not included** in this source snapshot. The design,
pin map, serial contract, slew limits, and failsafe behaviour are specified in
[`../smart-hvac-final-report.md`](../smart-hvac-final-report.md), Sections 7
and 8. Hardware verification is still pending.

When the sketch is added, place it here as:

```text
esp32/smart_hvac/smart_hvac.ino
```

## What the firmware is responsible for

The ESP32 does **not** detect people and does **not** apply the zone control
rule. It receives a six-integer percentage line over USB serial and:

1. maps each vent percentage to a servo angle;
2. maps the fan percentage to a 25 kHz PWM duty cycle;
3. moves all outputs gradually (at most 1 degree / 1 percentage point per
   20 ms tick);
4. prints a status line once per second;
5. enters **SAFE** (vents 50 %, fan 30 %) after 10 s without a valid command.

## Serial contract

```text
V,<ventA>,<ventB>,<ventC>,<ventD>,<fan>*<XOR>
```

- ASCII, 115200 baud, 8N1, newline-terminated.
- Six integers, each 0–100.
- `*<XOR>` is two upper-case hexadecimal digits: the XOR of every byte in the
  payload before the `*`.
- The laptop sends at 5 Hz and only while the newest camera frame is younger
  than 3 s.

The laptop side is implemented in [`../serial_link.py`](../serial_link.py).

## Pin map (from the report)

| Function | GPIO | Notes |
|---|---:|---|
| Servo A (vent 0) | 18 | Signal only; separate 5 V rail |
| Servo B (vent 1) | 19 | Signal only |
| Servo C (vent 2) | 21 | Signal only |
| Servo D (vent 3) | 22 | Signal only |
| Fan PWM (4-pin fan) | 23 | 25 kHz, 8-bit |
| Status LED | 2 | Onboard LED |
| Optional fan relay | 27 | Switches the fan's 12 V line |

All grounds must be common: 12 V adapter negative, buck converter negative,
servo ground, ESP32 ground, and fan ground.

## References

- Espressif Systems, *ESP32 Series Datasheet*: <https://www.espressif.com/en/products/socs/esp32>
- Espressif Systems, *Arduino-ESP32 documentation*: <https://docs.espressif.com/projects/arduino-esp32/en/latest/>
- Project reference list: [`../REFERENCES.md`](../REFERENCES.md)
