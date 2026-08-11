"""
Input management — serial encoder and keyboard, selected via config.

Provides a single ``InputManager`` that exposes a ``velocity`` property
regardless of which hardware backend is active.  The active mode is
chosen at construction time from ``InputConfig.mode``.
"""

from __future__ import annotations

import socket
import threading
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any, Optional

import serial
from direct.showbase import DirectObject
from direct.task.Task import Task

from mouseportal.clock import SessionClock

from mouseportal.config import InputConfig, InputMode

if TYPE_CHECKING:
    from direct.showbase.ShowBase import ShowBase


# ─── Shared data type ───────────────────────────────────────────────────────

@dataclass
class EncoderData:
    """A single rotary-encoder reading from the treadmill hardware.

    ``timestamp`` is the device's own microsecond clock.  ``received`` is the
    session clock reading when this sample reached MousePortal — both backends
    keep only the latest sample, so without it the age of the value a frame
    used would be unknowable.
    """
    timestamp: int = 0
    distance: float = 0.0
    speed: float = 0.0
    received: Optional[float] = None

    def __repr__(self) -> str:
        return (
            f"EncoderData(timestamp={self.timestamp}, "
            f"distance={self.distance:.3f} mm, speed={self.speed:.3f} mm/s)"
        )


def parse_encoder_csv(line: str) -> Optional[EncoderData]:
    """Parse one CSV encoder reading shared by the serial and network backends.

    Accepted formats:
      - ``timestamp,distance,speed`` (timestamp is the device microsecond clock)
      - ``distance,speed``

    Returns ``None`` for unparseable lines (headers, noise).
    """
    parts = line.split(",")
    try:
        if len(parts) == 3:
            return EncoderData(
                timestamp=int(float(parts[0].strip())),
                distance=float(parts[1].strip()),
                speed=float(parts[2].strip()),
            )
        elif len(parts) == 2:
            return EncoderData(
                distance=float(parts[0].strip()),
                speed=float(parts[1].strip()),
            )
    except ValueError:
        pass
    return None


# ─── Serial backend ─────────────────────────────────────────────────────────

class _SerialBackend(DirectObject.DirectObject):
    """
    Reads encoder data from a serial port (e.g. Teensy).

    Runs as a Panda3D per-frame task.  Parsed data is stored in
    ``self.data`` and broadcast via the messenger.
    """

    def __init__(self, port: str, baud: int, messenger: Any, clock: SessionClock) -> None:
        super().__init__()
        self._port = port
        self._baud = baud
        self._messenger = messenger
        self._clock = clock
        self.data = EncoderData()

        try:
            self._serial = serial.Serial(self._port, self._baud, timeout=1)
        except serial.SerialException as exc:
            raise RuntimeError(
                f"Failed to open serial port '{self._port}' at {self._baud} baud: {exc}"
            ) from exc

        self.accept("readSerial", self._store_data)

    # -- Panda3D task --------------------------------------------------

    def read_serial_task(self, task: Task) -> int:
        """Per-frame task: read one line from the serial port."""
        raw = self._serial.readline()
        received = self._clock.now()
        line = raw.decode("utf-8", errors="replace").strip()
        if line:
            data = self._parse_line(line)
            if data is not None:
                data.received = received
                self._messenger.send("readSerial", [data])
        return Task.cont

    # -- Internal ------------------------------------------------------

    def _store_data(self, data: EncoderData) -> None:
        self.data = data

    _parse_line = staticmethod(parse_encoder_csv)

    def close(self) -> None:
        """Release the serial port."""
        if self._serial and self._serial.is_open:
            self._serial.close()


# ─── Network backend ────────────────────────────────────────────────────────

class _NetworkBackend:
    """Receives encoder data forwarded over a localhost UDP socket.

    Mesofield owns the treadmill serial port and forwards each parsed sample
    (``device_us,distance,speed``) as a UDP datagram so MousePortal and the
    acquisition system never contend for the port.  A daemon thread keeps the
    latest reading in ``self.data``, stamped with its arrival time so a frame
    can report how stale the value it used was.
    """

    def __init__(self, host: str, port: int, clock: SessionClock) -> None:
        self.data = EncoderData()
        self._clock = clock
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self._sock.bind((host, port))
        except OSError as exc:
            raise RuntimeError(
                f"Failed to bind UDP socket {host}:{port}: {exc}"
            ) from exc
        self._sock.settimeout(0.5)
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._recv_loop, name="MousePortalUDP", daemon=True
        )
        self._thread.start()

    def _recv_loop(self) -> None:
        while not self._stop.is_set():
            try:
                raw, _addr = self._sock.recvfrom(256)
            except socket.timeout:
                continue
            except OSError:
                break
            received = self._clock.now()
            line = raw.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            data = parse_encoder_csv(line)
            if data is not None:
                data.received = received
                self.data = data

    @property
    def velocity(self) -> float:
        return self.data.speed

    def close(self) -> None:
        self._stop.set()
        try:
            self._sock.close()
        except OSError:
            pass


# ─── Keyboard backend ───────────────────────────────────────────────────────

class _KeyboardBackend:
    """Keyboard arrow-key input: sets a velocity when keys are held."""

    def __init__(self, base: "ShowBase", speed_scaling: float) -> None:
        self._base = base
        self._speed = speed_scaling
        self._key_state = {"forward": False, "backward": False}

        base.accept("arrow_up", self._set_key, ["forward", True])
        base.accept("arrow_up-up", self._set_key, ["forward", False])
        base.accept("arrow_down", self._set_key, ["backward", True])
        base.accept("arrow_down-up", self._set_key, ["backward", False])

    def _set_key(self, key: str, value: bool) -> None:
        self._key_state[key] = value

    @property
    def velocity(self) -> float:
        if self._key_state["forward"]:
            return self._speed
        if self._key_state["backward"]:
            return -self._speed
        return 0.0

    def close(self) -> None:
        pass


# ─── Unified InputManager ───────────────────────────────────────────────────

class InputManager:
    """
    Unified input facade.

    Depending on ``InputConfig.mode``, either a serial or keyboard
    backend is activated.  The rest of the application reads only
    ``input_manager.velocity``.
    """

    def __init__(
        self,
        base: "ShowBase",
        cfg: InputConfig,
        speed_scaling: float,
        clock: SessionClock,
        keyboard_speed: float = 20.0,
    ) -> None:
        self._mode = cfg.mode
        self._serial: Optional[_SerialBackend] = None
        self._keyboard: Optional[_KeyboardBackend] = None
        self._network: Optional[_NetworkBackend] = None

        if self._mode == InputMode.SERIAL:
            self._serial = _SerialBackend(
                cfg.serial_port, cfg.baud_rate, base.messenger, clock,
            )
            base.taskMgr.add(self._serial.read_serial_task, "readSerialTask")
        elif self._mode == InputMode.KEYBOARD:
            self._keyboard = _KeyboardBackend(base, keyboard_speed)
        elif self._mode == InputMode.NETWORK:
            self._network = _NetworkBackend(cfg.host, cfg.udp_port, clock)
        else:
            raise ValueError(f"Unknown input mode: {self._mode}")

    @property
    def velocity(self) -> float:
        """Current movement velocity from the active input source."""
        if self._mode == InputMode.SERIAL and self._serial is not None:
            return self._serial.data.speed
        if self._mode == InputMode.KEYBOARD and self._keyboard is not None:
            return self._keyboard.velocity
        if self._mode == InputMode.NETWORK and self._network is not None:
            return self._network.velocity
        return 0.0

    @property
    def last_sample(self) -> Optional[EncoderData]:
        """The most recent encoder reading, or ``None`` in keyboard mode.

        Carries the device microsecond clock MousePortal logs per frame for
        offline synchronisation with the mesofield cameras, and the session
        clock reading at which it arrived.  Only the serial and network
        backends have one.
        """
        if self._mode == InputMode.SERIAL and self._serial is not None:
            return self._serial.data
        if self._mode == InputMode.NETWORK and self._network is not None:
            return self._network.data
        return None

    def close(self) -> None:
        """Release resources held by the active backend."""
        if self._serial is not None:
            self._serial.close()
        if self._keyboard is not None:
            self._keyboard.close()
        if self._network is not None:
            self._network.close()
