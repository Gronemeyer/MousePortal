"""
Session timebase.

All logged times come from Panda3D's ``globalClock``, which is backed by
QueryPerformanceCounter: monotonic, ~100 ns resolution, and immune to NTP
steps.  Its epoch is process start, so a single Unix anchor captured at
startup converts any clock value to an epoch float for comparison with other
acquisition systems.

``time.time()`` is used only to establish that anchor.  On Windows it reports
GetSystemTimeAsFileTime with a nominal 15.625 ms resolution, which is coarser
than a frame — far too coarse to stamp rows with, but fine for a one-off
offset once the quantisation is measured and recorded.
"""

from __future__ import annotations

import time
from typing import Tuple

from panda3d.core import ClockObject

# The same object ShowBase publishes as the builtin ``globalClock``; imported
# explicitly so this module works before ShowBase has been constructed.
_clock = ClockObject.getGlobalClock()


def _anchor() -> Tuple[float, float, float]:
    """Pair a Unix epoch reading with a monotonic clock reading.

    Spins until ``time.time()`` ticks over, so the pairing lands on a system
    clock edge rather than anywhere inside a tick.  Returns
    ``(unix, clock, residual)`` where ``residual`` is the observed tick size —
    the bound on how far the epoch mapping can be off.
    """
    start = time.time()
    while True:
        unix = time.time()
        if unix != start:
            return unix, _clock.getRealTime(), unix - start


class SessionClock:
    """The session's single source of time.

    ``now()`` and ``frame_time()`` return monotonic seconds since process
    start; ``unix()`` maps either onto the Unix epoch.  Two clock values are
    distinguished deliberately:

    frame_time
        The value ``tick()`` set at the start of the current frame.  Identical
        for everything logged within one frame, which is what makes a frame's
        sample row and its events share a timestamp.
    now
        A fresh read.  Used to bracket the buffer flip, where sub-frame
        resolution is the whole point.
    """

    def __init__(self) -> None:
        self.unix_anchor, self.clock_anchor, self.anchor_residual = _anchor()

    def now(self) -> float:
        return _clock.getRealTime()

    def frame_time(self) -> float:
        return _clock.getFrameTime()

    def frame(self) -> int:
        return _clock.getFrameCount()

    def dt(self) -> float:
        return _clock.getDt()

    def unix(self, t: float) -> float:
        """Convert a monotonic clock value to a Unix epoch timestamp."""
        return self.unix_anchor + (t - self.clock_anchor)

    def describe(self) -> dict:
        """Anchor parameters for the timing sidecar."""
        return {
            "source": "panda3d.ClockObject.get_real_time (QueryPerformanceCounter)",
            "unix_anchor": self.unix_anchor,
            "clock_anchor": self.clock_anchor,
            "anchor_residual": self.anchor_residual,
            "formula": "unix = unix_anchor + (clock - clock_anchor)",
        }


class FixedClock(SessionClock):
    """Deterministic clock for simulation.

    Advances only when :meth:`step` is called, so a simulated session produces
    the same timestamps on every run.
    """

    def __init__(self, unix_start: float, dt: float) -> None:
        self.unix_anchor = unix_start
        self.clock_anchor = 0.0
        self.anchor_residual = 0.0
        self._dt = dt
        self._t = 0.0
        self._frame = 0

    def step(self) -> None:
        self._frame += 1
        self._t += self._dt

    def now(self) -> float:
        return self._t

    def frame_time(self) -> float:
        return self._t

    def frame(self) -> int:
        return self._frame

    def dt(self) -> float:
        return self._dt

    def describe(self) -> dict:
        return {
            "source": "mouseportal.clock.FixedClock (simulated)",
            "unix_anchor": self.unix_anchor,
            "clock_anchor": self.clock_anchor,
            "anchor_residual": self.anchor_residual,
            "formula": "unix = unix_anchor + (clock - clock_anchor)",
        }
