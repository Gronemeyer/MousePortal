"""
Position-based zone events — stub for future go/no-go paradigms.

A ``Zone`` is a corridor position range ``[start, end)`` with callbacks
for enter/exit.  The ``ZoneManager`` checks the camera position each
frame and fires events when boundaries are crossed.

This module is intentionally minimal.  It establishes the interface so
that wiring into the update loop is trivial when go/no-go is needed,
but adds no active behaviour today.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


@dataclass
class Zone:
    """A named corridor region between two Y positions."""
    label: str
    start: float
    end: float
    on_enter: Optional[Callable[["Zone"], None]] = None
    on_exit: Optional[Callable[["Zone"], None]] = None

    def contains(self, position: float) -> bool:
        return self.start <= position < self.end


class ZoneManager:
    """
    Tracks which zones the camera is inside and fires enter/exit events.

    Usage (future)::

        zm = ZoneManager()
        zm.add_zone(Zone("reward", 50.0, 55.0, on_enter=my_callback))
        # each frame:
        zm.update(camera_position)
    """

    def __init__(self) -> None:
        self._zones: List[Zone] = []
        self._active: set[str] = set()

    def add_zone(self, zone: Zone) -> None:
        """Register a zone."""
        self._zones.append(zone)

    def clear(self) -> None:
        """Remove all zones (e.g. between blocks)."""
        self._zones.clear()
        self._active.clear()

    def update(self, position: float) -> None:
        """Check position against all zones, fire enter/exit as needed."""
        for zone in self._zones:
            inside = zone.contains(position)
            was_inside = zone.label in self._active

            if inside and not was_inside:
                self._active.add(zone.label)
                if zone.on_enter is not None:
                    zone.on_enter(zone)
            elif not inside and was_inside:
                self._active.discard(zone.label)
                if zone.on_exit is not None:
                    zone.on_exit(zone)
