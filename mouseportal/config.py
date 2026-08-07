"""
Configuration dataclasses with validation for MousePortal.

All experiment parameters are defined here as typed dataclasses.
Configuration is loaded from JSON and validated at startup —
any invalid value raises immediately with a clear message.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


class InputMode(str, Enum):
    """Selects the active input source for corridor movement."""
    SERIAL = "serial"
    KEYBOARD = "keyboard"
    NETWORK = "network"   # velocity pushed over a localhost UDP socket


class TrialEndCondition(str, Enum):
    """How a trial is determined to have ended."""
    DISTANCE = "distance"   # Trial ends after a set distance traveled
    DURATION = "duration"   # Trial ends after a set time elapsed
    MANUAL = "manual"       # Trial ends on external trigger / keypress


# ─── Sub-configs ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class WindowConfig:
    width: int = 1920
    height: int = 1080
    # Top-left position of the window in the OS virtual-desktop pixel space.
    # On Windows, each monitor occupies a region of that shared space, so set
    # (origin_x, origin_y) to the top-left pixel of the monitor you want the
    # window to start on. To span two monitors, set width to the combined
    # width (e.g. 3840) and origin to the left monitor's top-left corner.
    # Leave as None to let the OS place the window.
    origin_x: Optional[int] = None
    origin_y: Optional[int] = None

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError(f"Window dimensions must be positive: {self.width}x{self.height}")


@dataclass(frozen=True)
class CorridorConfig:
    segment_length: float = 10.0
    corridor_width: float = 8.0
    wall_height: float = 10.0
    num_segments: int = 50
    left_wall_texture: str = "assets/test3.png"
    right_wall_texture: str = "assets/test3.png"
    ceiling_texture: str = "assets/white.png"
    floor_texture: str = "assets/black.png"

    def __post_init__(self) -> None:
        if self.segment_length <= 0:
            raise ValueError(f"segment_length must be positive: {self.segment_length}")
        if self.corridor_width <= 0:
            raise ValueError(f"corridor_width must be positive: {self.corridor_width}")
        if self.wall_height <= 0:
            raise ValueError(f"wall_height must be positive: {self.wall_height}")
        if self.num_segments < 3:
            raise ValueError(f"num_segments must be >= 3: {self.num_segments}")


@dataclass(frozen=True)
class CameraConfig:
    height: float = 2.0
    speed_scaling: float = 0.05    # multiplier for encoder speed (treadmill)
    keyboard_speed: float = 20.0   # units/sec when using arrow keys

    def __post_init__(self) -> None:
        if self.height < 0:
            raise ValueError(f"camera height must be non-negative: {self.height}")
        if self.speed_scaling <= 0:
            raise ValueError(f"speed_scaling must be positive: {self.speed_scaling}")
        if self.keyboard_speed <= 0:
            raise ValueError(f"keyboard_speed must be positive: {self.keyboard_speed}")


@dataclass(frozen=True)
class FogConfig:
    density: float = 0.06
    color: Tuple[float, float, float] = (0.5, 0.5, 0.5)

    def __post_init__(self) -> None:
        if self.density < 0:
            raise ValueError(f"fog density must be non-negative: {self.density}")
        if len(self.color) != 3 or not all(0.0 <= c <= 1.0 for c in self.color):
            raise ValueError(f"fog color must be 3 floats in [0,1]: {self.color}")


@dataclass(frozen=True)
class InputConfig:
    mode: InputMode = InputMode.KEYBOARD
    serial_port: str = "/dev/ttyUSB0"
    baud_rate: int = 57600
    # NETWORK mode: where to listen for forwarded encoder datagrams.
    host: str = "127.0.0.1"
    udp_port: int = 8765

    def __post_init__(self) -> None:
        if self.baud_rate <= 0:
            raise ValueError(f"baud_rate must be positive: {self.baud_rate}")
        if self.mode == InputMode.NETWORK and self.udp_port <= 0:
            raise ValueError(f"udp_port must be positive: {self.udp_port}")


@dataclass(frozen=True)
class TrialCondition:
    """Describes what happens during a single trial.

    The ``transform_type`` and ``transform_params`` fields select a
    :class:`~mouseportal.transforms.VelocityTransform` that is applied
    between raw input and camera movement.  Additional fields (e.g.
    texture overrides, trigger cues) can be added here for future
    paradigms like go/no-go without changing downstream code.

    Per-condition trial-end overrides
    ---------------------------------
    If ``trial_end_condition`` is set it takes precedence over the
    global ``ExperimentConfig.trial_end_condition`` for this condition.
    ``trial_distance`` and ``trial_duration`` work the same way.  When
    left as ``None`` the global value is used.
    """
    label: str = "normal"
    transform_type: str = "identity"
    transform_params: Dict[str, Any] = field(default_factory=dict)
    trial_end_condition: Optional[str] = None   # "distance", "duration", "manual"
    trial_distance: Optional[float] = None
    trial_duration: Optional[float] = None
    # Future go/no-go fields (uncomment when needed):
    # wall_texture_override: Optional[str] = None
    # trigger_on_enter: Optional[str] = None


@dataclass(frozen=True)
class ExperimentConfig:
    num_blocks: int = 1
    trials_per_block: int = 1
    iti_duration: float = 2.0
    trial_end_condition: TrialEndCondition = TrialEndCondition.MANUAL
    trial_distance: float = 100.0       # used when condition == DISTANCE
    trial_duration: float = 60.0        # used when condition == DURATION
    conditions: List[TrialCondition] = field(default_factory=list)
    block_conditions: List[Dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.num_blocks < 1:
            raise ValueError(f"num_blocks must be >= 1: {self.num_blocks}")
        if self.trials_per_block < 1:
            raise ValueError(f"trials_per_block must be >= 1: {self.trials_per_block}")
        if self.iti_duration < 0:
            raise ValueError(f"iti_duration must be non-negative: {self.iti_duration}")

    def condition_for(self, block: int, trial: int) -> TrialCondition:
        """Look up the condition for a given (1-indexed) block and trial.

        Falls back to ``TrialCondition()`` (identity / normal) when the
        config does not specify conditions.
        """
        if not self.block_conditions or not self.conditions:
            return TrialCondition()
        block_idx = block - 1
        trial_idx = trial - 1
        if block_idx < 0 or block_idx >= len(self.block_conditions):
            return TrialCondition()
        seq = self.block_conditions[block_idx].get("condition_sequence", [])
        if trial_idx < 0 or trial_idx >= len(seq):
            return TrialCondition()
        label = seq[trial_idx]
        for cond in self.conditions:
            if cond.label == label:
                return cond
        return TrialCondition()


@dataclass(frozen=True)
class TriggerConfig:
    enabled: bool = False
    port: str = ""
    baud_rate: int = 9600


@dataclass(frozen=True)
class LoggingConfig:
    subject: str = ""     # e.g. "001"
    session: str = ""     # e.g. "01"
    task: str = ""        # e.g. "corridor"
    output_dir: str = "data"  # root output directory (standalone use)
    output_path: str = ""     # explicit full CSV path (overrides BIDS layout)

    def __post_init__(self) -> None:
        if not self.subject:
            raise ValueError("logging.subject must be set (e.g. '001')")
        if not self.session:
            raise ValueError("logging.session must be set (e.g. '01')")
        if not self.task:
            raise ValueError("logging.task must be set (e.g. 'corridor')")

    def bids_path(self) -> str:
        """
        Resolve the output CSV path.

        If ``output_path`` is set (e.g. an orchestrator such as mesofield owns
        path construction and hands MousePortal the exact file), it is used
        verbatim — MousePortal does NOT build its own directory layout.
        Otherwise a BIDS-compliant path is built under ``output_dir`` for
        standalone use, e.g.
        ``data/sub-001/ses-01/beh/sub-001_ses-01_task-corridor_portal.csv``.
        """
        if self.output_path:
            return self.output_path
        import os
        sub = f"sub-{self.subject}"
        ses = f"ses-{self.session}"
        beh_dir = os.path.join(self.output_dir, sub, ses, "beh")
        filename = f"{sub}_{ses}_task-{self.task}_portal.csv"
        return os.path.join(beh_dir, filename)


# ─── Top-level config ───────────────────────────────────────────────────────

@dataclass(frozen=True)
class PortalConfig:
    """Top-level configuration that composes all sub-configs."""
    window: WindowConfig = field(default_factory=WindowConfig)
    corridor: CorridorConfig = field(default_factory=CorridorConfig)
    camera: CameraConfig = field(default_factory=CameraConfig)
    fog: FogConfig = field(default_factory=FogConfig)
    input: InputConfig = field(default_factory=InputConfig)
    experiment: ExperimentConfig = field(default_factory=ExperimentConfig)
    triggers: TriggerConfig = field(default_factory=TriggerConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)

    # ─── Loaders ────────────────────────────────────────────────────────
    @classmethod
    def from_json(cls, path: str) -> "PortalConfig":
        """
        Load and validate configuration from a JSON file.

        Raises on any I/O or validation error (fail-fast).
        Accepts both the new nested schema and the legacy flat schema
        produced by prior versions (``cfg.json`` v0.2).
        """
        try:
            with open(path, "r") as fh:
                raw: Dict[str, Any] = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Failed to load config '{path}': {exc}") from exc

        # Detect legacy flat config (has top-level "segment_length" key)
        if "segment_length" in raw:
            return cls._from_legacy(raw)

        return cls(
            window=WindowConfig(**raw.get("window", {})),
            corridor=CorridorConfig(**raw.get("corridor", {})),
            camera=CameraConfig(**raw.get("camera", {})),
            fog=FogConfig(**_parse_fog(raw.get("fog", {}))),
            input=InputConfig(**_parse_input(raw.get("input", {}))),
            experiment=ExperimentConfig(**_parse_experiment(raw.get("experiment", {}))),
            triggers=TriggerConfig(**raw.get("triggers", {})),
            logging=LoggingConfig(**raw.get("logging", {"subject": "000", "session": "00", "task": "portal"})),
        )

    @classmethod
    def _from_legacy(cls, raw: Dict[str, Any]) -> "PortalConfig":
        """Map the flat v0.2 cfg.json keys to the nested structure."""
        return cls(
            window=WindowConfig(
                width=raw.get("window_width", 1920),
                height=raw.get("window_height", 1080),
                origin_x=raw.get("window_origin_x"),
                origin_y=raw.get("window_origin_y"),
            ),
            corridor=CorridorConfig(
                segment_length=raw.get("segment_length", 10.0),
                corridor_width=raw.get("corridor_width", 8.0),
                wall_height=raw.get("wall_height", 10.0),
                num_segments=raw.get("num_segments", 50),
                left_wall_texture=raw.get("left_wall_texture", "assets/test3.png"),
                right_wall_texture=raw.get("right_wall_texture", "assets/test3.png"),
                ceiling_texture=raw.get("ceiling_texture", "assets/white.png"),
                floor_texture=raw.get("floor_texture", "assets/black.png"),
            ),
            camera=CameraConfig(
                height=raw.get("camera_height", 2.0),
                speed_scaling=raw.get("speed_scaling", 0.05),
                keyboard_speed=raw.get("keyboard_speed", 20.0),
            ),
            fog=FogConfig(
                density=raw.get("fog_density", 0.06),
                color=tuple(raw.get("fog_color", [0.5, 0.5, 0.5])),
            ),
            input=InputConfig(
                mode=InputMode(raw.get("input_mode", "keyboard")),
                serial_port=raw.get("serial_port", "/dev/ttyUSB0"),
                baud_rate=raw.get("baud_rate", 57600),
            ),
            experiment=ExperimentConfig(),
            triggers=TriggerConfig(),
            logging=LoggingConfig(
                subject=raw.get("subject", "000"),
                session=raw.get("session", "00"),
                task=raw.get("task", "portal"),
                output_dir=raw.get("output_dir", "data"),
            ),
        )


# ─── Parsing helpers (normalise JSON → dataclass kwargs) ────────────────────

def _parse_fog(d: Dict[str, Any]) -> Dict[str, Any]:
    """Convert fog JSON (color may be a list) to FogConfig kwargs."""
    out = dict(d)
    if "color" in out and isinstance(out["color"], list):
        out["color"] = tuple(out["color"])
    return out


def _parse_input(d: Dict[str, Any]) -> Dict[str, Any]:
    """Convert input JSON (mode is a string) to InputConfig kwargs."""
    out = dict(d)
    if "mode" in out and isinstance(out["mode"], str):
        out["mode"] = InputMode(out["mode"])
    return out


def _parse_experiment(d: Dict[str, Any]) -> Dict[str, Any]:
    """Convert experiment JSON to ExperimentConfig kwargs."""
    out = dict(d)
    if "trial_end_condition" in out and isinstance(out["trial_end_condition"], str):
        out["trial_end_condition"] = TrialEndCondition(out["trial_end_condition"])
    # Parse conditions list → TrialCondition instances
    if "conditions" in out and isinstance(out["conditions"], list):
        out["conditions"] = [
            TrialCondition(**c) if isinstance(c, dict) else c
            for c in out["conditions"]
        ]
    return out
