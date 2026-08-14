"""
Session logging for MousePortal.

Three tables at three grains, each with a fully-populated schema:

samples
    One row per rendered frame — the continuous record.
events
    One row per discrete occurrence, in long format.
trials
    One row per completed trial — the summary the analysis joins against.

A ``timing.json`` sidecar carries the clock anchor, the display settings, and
the measured refresh statistics, so a reader can convert timestamps and judge
their accuracy without reading this file.

Absent values are written as ``n/a``: it is the BIDS convention and pandas
parses it as NaN by default.  Splitting the tables is what removes most nulls
in the first place; ``n/a`` covers what genuinely varies, such as a device
clock in keyboard mode.

An optional ``on_row`` callback provides a hook for future IPC (pipe, socket,
ZMQ) without changing the logger API.
"""

from __future__ import annotations

import csv
import json
import os
from collections import deque
from typing import Any, Callable, Deque, Dict, Iterable, Optional

NA = "n/a"

# Only frames in this state count toward the trial summary; the ITI frames
# between TRIAL_END and the next TRIAL_START belong to no trial.
TRIAL_STATE = "TRIAL_RUNNING"

SAMPLE_FIELDS = [
    "frame",
    "timestamp",
    "flip_timestamp",
    "flip_wait",
    "frame_dt",
    "dropped",
    "sync_level",
    "state",
    "block",
    "trial",
    "condition",
    "position",
    "velocity",
    "effective_velocity",
    "treadmill_device_us",
    "treadmill_age",
]

EVENT_FIELDS = [
    "timestamp",
    "flip_timestamp",
    "frame",
    "block",
    "trial",
    "event",
    "condition",
    "value",
]

TRIAL_FIELDS = [
    "block",
    "block_name",
    "trial",
    "condition",
    "transform",
    "transform_params",
    "start_timestamp",
    "end_timestamp",
    "duration",
    "distance",
    "end_rule",
    "n_frames",
    "n_dropped",
    "mean_velocity",
    "mean_effective_velocity",
]

# Units and meaning for every column, emitted into the sidecar so the tables
# are self-describing.
COLUMN_DOC = {
    "samples": {
        "frame": ["", "Panda3D global frame count; the join key across all streams"],
        "timestamp": ["s", "Unix epoch of the start of this frame (globalClock frame time)"],
        "flip_timestamp": ["s", "Unix epoch immediately after the buffer swap returned"],
        "flip_wait": ["s", "Time blocked inside flipFrame(); near zero means the vblank was missed"],
        "frame_dt": ["s", "Interval between the previous two frame ticks"],
        "dropped": ["", "1 when the flip interval exceeded the dropped-frame threshold"],
        "sync_level": ["", "Luminance commanded for the photodiode patch on this frame"],
        "state": ["", "Experiment state machine state"],
        "block": ["", "Block index, 1-based; 0 before the session starts"],
        "trial": ["", "Trial index within the block, 1-based; 0 before the session starts"],
        "condition": ["", "Active trial condition label"],
        "position": ["corridor units", "Camera position along the corridor"],
        "velocity": ["corridor units/s", "Raw input velocity before the transform"],
        "effective_velocity": ["corridor units/s", "Velocity after the trial's transform"],
        "treadmill_device_us": ["us", "Treadmill device clock of the most recent sample"],
        "treadmill_age": ["s", "Age of that device sample at this frame's start"],
    },
    "events": {
        "timestamp": ["s", "Unix epoch of the frame in which the event was recorded"],
        "flip_timestamp": ["s", "Presentation time of that frame; n/a when the event had no visual consequence"],
        "frame": ["", "Panda3D global frame count"],
        "block": ["", "Block index, 1-based"],
        "trial": ["", "Trial index within the block, 1-based"],
        "event": ["", "Event token"],
        "condition": ["", "Active trial condition label"],
        "value": ["", "Scalar payload; meaning depends on the event token"],
    },
    "trials": {
        "block": ["", "Block index, 1-based"],
        "block_name": ["", "Block name from the config; n/a when the block is unnamed"],
        "trial": ["", "Trial index within the block, 1-based"],
        "condition": ["", "Trial condition label"],
        "transform": ["", "Velocity transform type"],
        "transform_params": ["", "JSON object of transform parameters"],
        "start_timestamp": ["s", "Unix epoch at TRIAL_START"],
        "end_timestamp": ["s", "Unix epoch at TRIAL_END"],
        "duration": ["s", "end_timestamp - start_timestamp"],
        "distance": ["corridor units", "Distance travelled during the trial"],
        "end_rule": ["", "Resolved trial-end rule: distance, duration, or manual"],
        "n_frames": ["", "Frames rendered during the trial"],
        "n_dropped": ["", "Frames flagged dropped during the trial"],
        "mean_velocity": ["corridor units/s", "Mean raw input velocity over the trial"],
        "mean_effective_velocity": ["corridor units/s", "Mean post-transform velocity over the trial"],
    },
}


class _TrialAccumulator:
    """Running totals for the trial summary row."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.n_frames = 0
        self.n_dropped = 0
        self._velocity_sum = 0.0
        self._effective_sum = 0.0

    def add(self, velocity: float, effective_velocity: float, dropped: int) -> None:
        self.n_frames += 1
        self.n_dropped += dropped
        self._velocity_sum += velocity
        self._effective_sum += effective_velocity

    @property
    def mean_velocity(self) -> Any:
        return self._velocity_sum / self.n_frames if self.n_frames else NA

    @property
    def mean_effective_velocity(self) -> Any:
        return self._effective_sum / self.n_frames if self.n_frames else NA


class SessionLogger:
    """
    Writes the three session tables and the timing sidecar.

    Files are created exclusively, so a rerun with the same subject/session
    never appends to a previous run's data.  Implements the context-manager
    protocol::

        with SessionLogger(cfg.logging, clock, header) as log:
            log.write_sample(...)
    """

    def __init__(
        self,
        stem: str,
        header: Dict[str, Any],
        dropped_frame_threshold: float,
        on_row: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    ) -> None:
        self.stem = stem
        self._header = header
        self._threshold = dropped_frame_threshold
        self._on_row = on_row

        parent = os.path.dirname(stem)
        if parent:
            os.makedirs(parent, exist_ok=True)

        self._files = {}
        self._writers = {}
        for stream, fields in (
            ("samples", SAMPLE_FIELDS),
            ("events", EVENT_FIELDS),
            ("trials", TRIAL_FIELDS),
        ):
            fh = open(f"{stem}-{stream}.csv", "x", newline="")
            writer = csv.DictWriter(fh, fieldnames=fields, restval=NA)
            writer.writeheader()
            self._files[stream] = fh
            self._writers[stream] = writer

        self.n_frames = 0
        self.n_dropped = 0
        self.trial = _TrialAccumulator()
        self._prev_flip: Optional[float] = None
        self._flip_intervals: Deque[float] = deque(maxlen=600)
        self._interval_count = 0
        self._refresh_interval: Optional[float] = None
        self.write_sidecar()

    # -- Context manager -----------------------------------------------

    def __enter__(self) -> "SessionLogger":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # -- Public API ----------------------------------------------------

    def write_sample(self, row: Dict[str, Any]) -> None:
        """Write one frame row. ``row`` is filled by the caller's flip task."""
        self.n_frames += 1
        self.n_dropped += row["dropped"]
        if row["state"] == TRIAL_STATE:
            self.trial.add(row["velocity"], row["effective_velocity"], row["dropped"])
        self._emit("samples", row)
        # Refresh the sidecar periodically so a session that is killed rather
        # than closed still carries its measured timing.
        if self.n_frames % 600 == 0:
            self.write_sidecar()

    def write_event(self, row: Dict[str, Any]) -> None:
        self._emit("events", row)

    def write_trial(self, row: Dict[str, Any]) -> None:
        self._emit("trials", row)
        self.trial.reset()

    def classify_flip(self, flip_timestamp: float) -> int:
        """Return 1 when this flip arrived too late to be a single refresh.

        The threshold rides on the running median of observed flip intervals
        rather than the display's nominal rate, so it adapts to whatever the
        window is actually running at.  Nothing is flagged until the first 120
        intervals have established that median.
        """
        dropped = 0
        if self._prev_flip is not None:
            interval = flip_timestamp - self._prev_flip
            self._flip_intervals.append(interval)
            self._interval_count += 1
            if self._refresh_interval is not None:
                dropped = int(interval > self._refresh_interval * self._threshold)
            if self._interval_count % 120 == 0:
                self._refresh_interval = _median(self._flip_intervals)
        self._prev_flip = flip_timestamp
        return dropped

    @property
    def measured_refresh_interval(self) -> Any:
        return self._refresh_interval if self._refresh_interval is not None else NA

    def write_sidecar(self) -> None:
        """Write timing.json. Called at open and again at close with results."""
        doc = dict(self._header)
        doc["display"] = dict(doc["display"])
        doc["display"]["measured_refresh_interval"] = self.measured_refresh_interval
        doc["display"]["n_frames"] = self.n_frames
        doc["display"]["n_dropped"] = self.n_dropped
        doc["columns"] = COLUMN_DOC
        with open(f"{self.stem}-timing.json", "w") as fh:
            json.dump(doc, fh, indent=2)

    def close(self) -> None:
        """Finalise the sidecar and close the tables."""
        self.write_sidecar()
        for fh in self._files.values():
            if not fh.closed:
                fh.flush()
                fh.close()

    # -- Internal ------------------------------------------------------

    def _emit(self, stream: str, row: Dict[str, Any]) -> None:
        self._writers[stream].writerow(row)
        self._files[stream].flush()
        if self._on_row is not None:
            self._on_row(stream, row)


def _median(values: Iterable[float]) -> float:
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return 0.5 * (ordered[mid - 1] + ordered[mid])
