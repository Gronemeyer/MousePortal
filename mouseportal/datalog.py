"""
Data logging for MousePortal.

Writes a single CSV with both continuous per-frame data and discrete
experiment events.  An optional ``on_row`` callback provides a hook
for future IPC (pipe, socket, ZMQ) without changing the logger API.
"""

from __future__ import annotations

import csv
import os
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional


class DataLogger:
    """
    Logs per-frame movement data and experiment events to a CSV file.

    Implements the context-manager protocol so the file handle is
    always closed cleanly::

        with DataLogger("data.csv") as log:
            log.log_frame(...)
    """

    FIELDNAMES = [
        "timestamp",
        "datetime",
        "frame",
        "state",
        "block",
        "trial",
        "condition",
        "position",
        "velocity",
        "effective_velocity",
        "event",
    ]

    def __init__(
        self,
        filename: str,
        on_row: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> None:
        self.filename = filename
        self._on_row = on_row
        self._frame: int = 0

        # Ensure parent directories exist (for BIDS paths).
        parent = os.path.dirname(self.filename)
        if parent:
            os.makedirs(parent, exist_ok=True)

        file_exists = os.path.isfile(self.filename)
        self._file = open(self.filename, "a", newline="")
        self._writer = csv.DictWriter(self._file, fieldnames=self.FIELDNAMES)
        if not file_exists:
            self._writer.writeheader()

    # -- Context manager -----------------------------------------------

    def __enter__(self) -> "DataLogger":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # -- Public API ----------------------------------------------------

    def log_frame(
        self,
        position: float,
        velocity: float,
        effective_velocity: float = 0.0,
        condition: str = "",
        state: str = "",
        block: int = 0,
        trial: int = 0,
        event: str = "",
    ) -> None:
        """Write one row of per-frame data."""
        self._frame += 1
        now = time.time()
        row: Dict[str, Any] = {
            "timestamp": now,
            "datetime": datetime.fromtimestamp(now, tz=timezone.utc).isoformat(),
            "frame": self._frame,
            "state": state,
            "block": block,
            "trial": trial,
            "condition": condition,
            "position": position,
            "velocity": velocity,
            "effective_velocity": effective_velocity,
            "event": event,
        }
        self._writer.writerow(row)
        self._file.flush()
        if self._on_row is not None:
            self._on_row(row)

    def log_event(self, event_type: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        """Write a discrete event row (no position/velocity)."""
        now = time.time()
        row: Dict[str, Any] = {
            "timestamp": now,
            "datetime": datetime.fromtimestamp(now, tz=timezone.utc).isoformat(),
            "frame": self._frame,
            "state": "",
            "block": 0,
            "trial": 0,
            "position": "",
            "velocity": "",
            "event": event_type,
        }
        if metadata:
            # Merge extra keys into the event field as JSON-ish string
            row["event"] = f"{event_type}|{metadata}"
        self._writer.writerow(row)
        self._file.flush()
        if self._on_row is not None:
            self._on_row(row)

    def close(self) -> None:
        """Flush and close the CSV file."""
        if not self._file.closed:
            self._file.flush()
            self._file.close()
