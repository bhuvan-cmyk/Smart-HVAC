"""Serial link between the laptop (Python) and the ESP32.

Provides a SerialLink class that opens the USB port, sends percentage lines,
and falls back to a DummyLink when no hardware port is available.  The protocol
is ASCII, 115200 baud, newline-terminated.  Lines are six integer fields
comma-separated: V,A,B,C,D,FAN with each value 0–100.

Public API
----------
class SerialLink
    __init__(port="auto")          # port name or "auto"
    open()                         # open port, wait for ESP32 reset
    send(vents, fan)               # send V,a,b,c,d*HH line
    close()                        # close port
    property connected -> bool     # True if last S line seen < 3 s ago
 class DummyLink
    __init__(label="dummy")
    send(vents, fan)               # print the line it would send
    close()                        # no-op
"""

import sys
import time
import logging
import platform
from pathlib import Path
import serial  # pyserial

from config import SEND_PERIOD_S, FRAME_FRESH_S

logger = logging.getLogger("smart-hvac.serial")


# ---------------------------------------------------------------------------
# XOR checksum helpers
# ---------------------------------------------------------------------------

def _xor_checksum(payload: str) -> str:
    """Compute the XOR of all bytes in payload, returned as two upper-case hex digits."""
    x = 0
    for ch in payload.encode("ascii"):
        x ^= ch
    return f"{x:02X}"


def _make_line(payload: str) -> str:
    """Append XOR checksum to a payload string.

    Example: _make_line("V,15,66,15,100,84") -> "V,15,66,15,100,84*45"
    """
    return f"{payload}*{_xor_checksum(payload)}"


# ---------------------------------------------------------------------------
# Dummy link — used when no serial port is available
# ---------------------------------------------------------------------------

class DummyLink:
    """A no-op serial link that prints the line it would send.

    Useful for demonstration and testing when no ESP32 is connected.
    """

    def __init__(self, label: str = "dummy"):
        self._label = label
        self._last_printed = 0.0

    def send(self, vents, fan):
        """Print the V line that would be sent to the ESP32.

        Args:
            vents: list/tuple of four integers 0–100 [A,B,C,D].
            fan: integer 0–100.
        """
        now = time.time()
        # At most once per second
        if now - self._last_printed < 1.0:
            return
        a, b, c, d = map(int, vents)
        line = f"V,{a},{b},{c},{d},{int(fan)}"
        print(f"[DummyLink] {line}")
        self._last_printed = now

    def close(self):
        """No-op."""  # noqa: D401


# ---------------------------------------------------------------------------
# Main serial link
# ---------------------------------------------------------------------------

class SerialLink:
    """Laptop → ESP32 serial link.

    After opening the port, waits 2 s (ESP32 reset), then flushes.
    Sends percentage lines at SEND_PERIOD_S (5 Hz) only if a frame younger
    than FRAME_FRESH_S (3 s) was processed since the last send.

    If the port cannot be opened, falls back to DummyLink.  Never crashes.
    """

    # --- port auto-detection ---
    AUTO_KEYWORDS = ["CP210", "CH340", "USB-SERIAL"]

    def __init__(self, port: str = "auto"):
        """Initialise the serial link.

        Args:
            port: one of
                - "auto": autodetect the first port whose description contains
                  CP210, CH340 or USB-SERIAL
                - a Windows COM name like "COM5"
                - a Linux device like "/dev/ttyUSB0"
                - "dummy" to use the DummyLink
        """
        self._port_name = port
        self._ser = None
        self._dummy = None
        self._last_send = 0.0
        self._last_s_line = ""
        self._last_s_ts = 0.0
        self._connected = False
        self._open_attempts = 0

    def _auto_detect(self) -> str | None:
        """Try to auto-detect a serial port for the ESP32.

        Returns the port name if found, else None.
        """
        import serial.tools.list_ports as lp
        for p in lp.comports():
            desc = p.description or ""
            for kw in self.AUTO_KEYWORDS:
                if kw in desc:
                    return p.device
        return None

    def open(self):
        """Open the serial port, wait for the ESP32 reset, and prepare to send.

        Behavior:
          1. If port is "auto", try to detect a CP210/CH340/USB-SERIAL port.
          2. If not found, fall back to "dummy".
          3. Open the port at 115200 baud, 8N1.
          4. Wait up to 3 s for the ESP32 to print "READY" (harmless if missing).
          5. Flush the input buffer.
          6. If the port cannot be opened, log a warning and use DummyLink.

        Never raises an exception.
        """
        # Determine the actual port name
        if self._port_name == "auto":
            detected = self._auto_detect()
            if detected:
                self._port_name = detected
                logger.info(f"Auto-detected serial port: {self._port_name}")
            else:
                self._port_name = "dummy"
                logger.warning(
                    "No auto-detected serial port. Falling back to DummyLink. "
                    "Connect an ESP32 or use --port dummy."
                )

        # If we are already on dummy, just initialise it
        if self._port_name == "dummy":
            self._dummy = DummyLink("main")
            self._ser = None
            self._connected = False
            logger.info("Using DummyLink for serial communication")
            return

        # Try to open the real serial port
        try:
            self._ser = serial.Serial(
                port=self._port_name,
                baudrate=115200,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=2.0,          # read timeout
                write_timeout=2.0,
            )
            # Wait for the ESP32 to reset and print "READY".
            # We tolerate the reset by waiting and then continuing regardless.
            deadline = time.time() + 3.0
            ready = False
            while time.time() < deadline:
                if self._ser.in_waiting:
                    line = self._ser.readline().decode("utf-8", errors="replace").strip()
                    if line.startswith("READY"):
                        ready = True
                        break
                time.sleep(0.1)

            # Flush the input buffer so we don't act on stale data
            self._ser.reset_input_buffer()

            self._connected = True
            logger.info(f"Serial port {self._port_name} opened. Connected={self._connected}")
        except serial.SerialException as e:
            logger.warning(f"Could not open serial port {self._port_name}: {e}")
            self._ser = None
            self._dummy = DummyLink("main")
            self._connected = False
            self._port_name = "dummy"
        except Exception as e:
            logger.warning(f"Unexpected error opening serial port: {e}")
            self._ser = None
            self._dummy = DummyLink("main")
            self._connected = False
            self._port_name = "dummy"

    def send(self, vents, fan):
        """Send a vent/fan percentage line to the ESP32.

        Format: V,A,B,C,D,FAN*HH  (six integers 0–100, XOR checksum).

        The line is sent only if enough time has passed (SEND_PERIOD_S) and the
        most recent camera frame is younger than FRAME_FRESH_S (3 s).

        Args:
            vents: list/tuple of four integers 0–100 [A, B, C, D].
            fan: integer 0–100.
        """
        # Enforce send period
        now = time.time()
        if now - self._last_send < SEND_PERIOD_S:
            return

        # Check that the newest frame is still fresh
        # (the caller should ensure self._ser is not None when a fresh frame exists)
        if self._ser is None:
            # Fall back to dummy
            if self._dummy is not None:
                self._dummy.send(vents, fan)
            self._last_send = now
            return

        a, b, c, d = map(int, vents)
        fan_int = int(fan)
        payload = f"V,{a},{b},{c},{d},{fan_int}"
        line = _make_line(payload)

        try:
            self._ser.write((line + "\n").encode("ascii"))
            self._last_send = now
        except serial.SerialException:
            # Port died — fall back to dummy
            logger.warning("Serial port error during send; falling back to DummyLink")
            self._ser = None
            if self._dummy is None:
                self._dummy = DummyLink("main")
            self._dummy.send(vents, fan)

    def process_s_line(self, line: str):
        """Parse an incoming S line from the ESP32.

        Expected format: S,MODE,angA,angB,angC,angD,fanPct,age_ms

        Updates the internal state with the latest MODE and actual percentages.

        Args:
            line: the full S line string (without trailing newline).
        """
        try:
            parts = line.strip().split(",")
            if len(parts) != 8:
                logger.warning(f"Malformed S line (expected 8 fields, got {len(parts)}): {line!r}")
                return
            mode = parts[1]
            angA, angB, angC, angD = map(int, parts[2:6])
            fan_pct = int(parts[6])
            age_ms = int(parts[7])

            self._last_s_line = line
            self._last_s_ts = time.time()
            self._connected = (age_ms < 3000)  # connected if fresh

            logger.debug(f"S line: mode={mode} angles={angA},{angB},{angC},{angD} fan={fan_pct} age_ms={age_ms}")
        except (ValueError, IndexError) as e:
            logger.warning(f"Failed to parse S line: {e} — line: {line!r}")

    def close(self):
        """Close the serial port if open."""
        if self._ser is not None:
            try:
                self._ser.close()
            except Exception:
                pass
            self._ser = None
        if self._dummy is not None:
            self._dummy.close()
            self._dummy = None
        logger.info("Serial link closed")

    @property
    def connected(self) -> bool:
        """True if a valid S line has been received within the last 3 s."""
        if self._ser is None:
            # When using dummy, we consider "connected" as whatever the dummy reports
            return False
        elapsed = (time.time() - self._last_s_ts) * 1000  # ms
        return elapsed < 3000

    @property
    def port(self) -> str:
        """Return the port name being used (or 'dummy')."""
        return self._port_name if self._ser is not None else "dummy"