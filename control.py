"""Pure-control functions for the Smart HVAC system.

No I/O here — these are deterministic functions that map counts → vent%
and counts → fan %.  All arithmetic uses round-half-up (floor(x + 0.5)) so
the laptop and ESP32 always agree.  Constants are from config.py.

Public functions
----------------
vent_percentages(counts) -> list[int]  # four vent openings 0–100
fan_percent(total) -> int               # fan opening 0–100
Controller.update(counts, now) -> dict  # mode, vents, fan
"""

from config import (VENT_MIN, VENT_MAX, FAN_MIN, FAN_MAX,
                    FAN_FULL_AT, IDLE_DELAY_S, SMOOTH_WINDOW_CONTROL,
                    round_half_up)


def vent_percentages(counts: list[int], maxc: int) -> list[int]:
    """Return vent opening percentages for four zones.

    The rule (from Section 5.4):
      - If total occupancy is 0: all vents 0 % (closed).
      - If max count is 0 but total > 0 (should not happen): all 15 %.
      - Otherwise: vent_i = 15 + 85 × c_i / maxc, rounded half-up.
        The busiest zone always reaches exactly 100 %.

    Args:
        counts: per-zone smoothed counts [cA, cB, cC, cD].
        maxc: the maximum of the four counts.

    Returns:
        list of four integers 0–100, one per zone A–D.
    """
    total = sum(counts)
    if total == 0:
        return [0, 0, 0, 0]
    if maxc == 0:
        return [15, 15, 15, 15]
    return [round_half_up(15 + 85 * c / maxc) for c in counts]


def fan_percent(total: int) -> int:
    """Return fan speed percentage.

    The rule (from Section 5.5):
      - If total == 0: 0 % (IDLE, minimum PWM).
      - Otherwise: 20 + 80 × total ÷ 10, capped at 100.
        Integer math: 20 + 8 * total, never exceeds 100 for total ≤ 10,
        but we cap anyway.

    Args:
        total: total occupancy (sum of all zone counts + unzoned).

    Returns:
        integer 0–100.
    """
    if total == 0:
        return 0
    return min(100, 20 + 8 * total)


class Controller:
    """Control loop state machine.

    Handles the empty-room hold (IDLE_DELAY_S) and mode transitions.
    """

    def __init__(self):
        self._prev_vents = [0, 0, 0, 0]
        self._prev_fan = 0
        self._empty_since = None          # timestamp when total first became 0
        self._in_idle = False

    def update(self, counts: list[int], now: float) -> dict:
        """Compute the current mode and vent/fan outputs.

        Args:
            counts: per-zone smoothed counts [cA, cB, cC, cD].
            now: current time (seconds), used for the empty-room hold.

        Returns:
            dict with keys:
                - "mode": one of "NORMAL", "IDLE", "SAFE"
                - "vents": list of four integers 0–100
                - "fan": integer 0–100
        """
        total = sum(counts)

        if total > 0:
            # People are present — transition out of IDLE immediately
            self._in_idle = False
            self._empty_since = None
            vents = vent_percentages(counts, max(counts))
            fan = fan_percent(total)
            mode = "NORMAL"
        else:
            # Total is zero — check the idle hold
            if not self._in_idle:
                # First time we see zero; start the hold timer
                self._in_idle = True
                self._empty_since = now

            # Check if we have held zero long enough
            hold_time = now - self._empty_since if self._empty_since else 0.0
            if hold_time >= IDLE_DELAY_S:
                # Confirmed empty: enter IDLE
                self._in_idle = True
                vents = [0, 0, 0, 0]
                fan = 0  # minimum PWM
                mode = "IDLE"
            else:
                # Still within the hold period: keep previous outputs
                vents = self._prev_vents
                fan = self._prev_fan
                mode = "NORMAL"  # still normal, just holding last values

        # Store for next iteration's hold-period fallback
        self._prev_vents = list(vents)
        self._prev_fan = fan

        return {"mode": mode, "vents": vents, "fan": fan}