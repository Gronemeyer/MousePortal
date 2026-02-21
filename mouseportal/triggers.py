"""
Trigger output manager — reward delivery and cue signals.

Provides a minimal, extensible interface for sending hardware
triggers (e.g. serial TTL pulses to a reward valve or cue LED).
When ``TriggerConfig.enabled`` is False, all methods are silent
no-ops so the rest of the code never needs to check.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from mouseportal.config import TriggerConfig


class TriggerManager:
    """
    Sends reward / cue trigger signals to external hardware.

    Currently supports serial output.  When disabled in config,
    every public method is a no-op.
    """

    def __init__(self, cfg: "TriggerConfig") -> None:
        self._enabled = cfg.enabled
        self._serial = None

        if self._enabled:
            import serial as _serial

            try:
                self._serial = _serial.Serial(cfg.port, cfg.baud_rate, timeout=1)
            except _serial.SerialException as exc:
                raise RuntimeError(
                    f"Trigger serial port '{cfg.port}' failed to open: {exc}"
                ) from exc

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def send_reward(self) -> None:
        """Send a reward trigger pulse."""
        self._write(b"R\n")

    def send_cue(self, cue_type: str = "default") -> None:
        """Send a cue trigger with an identifier string."""
        self._write(f"C:{cue_type}\n".encode("ascii"))

    def close(self) -> None:
        """Release the serial port."""
        if self._serial is not None and self._serial.is_open:
            self._serial.close()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _write(self, data: bytes) -> None:
        if not self._enabled or self._serial is None:
            return
        try:
            self._serial.write(data)
        except Exception:
            # In a real experiment you may want to log this.
            pass
