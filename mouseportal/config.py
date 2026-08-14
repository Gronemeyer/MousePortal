"""
Configuration dataclasses with validation for MousePortal.

All experiment parameters are defined here as typed dataclasses.
Configuration is loaded from JSON and validated at startup —
any invalid value raises immediately with a clear message.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field, fields
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Tuple


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


# Transforms that discard the subject's input entirely. A distance-ended trial
# of one of these cannot be ended by the subject's running, so the combination
# is rejected at load rather than left to stall the session.
_OPEN_LOOP_TRANSFORMS = frozenset({"freeze", "reverse"})


def default_seed() -> int:
    """Today's date as ``YYYYMMDD`` — the seed used when none is configured.

    A date reads as what it is in the sidecar and in a lab notebook, which a
    random 31-bit integer does not.  Note the consequence: every session run on
    the same day with no explicit seed draws the same ITI lengths and the same
    shuffled block orders.  Set ``random_seed`` explicitly per subject when
    that matters.
    """
    from datetime import date
    return int(date.today().strftime("%Y%m%d"))


def _check_iti_range(iti_range: Optional[Sequence[float]], where: str) -> None:
    """Validate an ``[min, max]`` ITI range. ``None`` means "unset", which is fine."""
    if iti_range is None:
        return
    if len(iti_range) != 2:
        raise ValueError(f"{where} must be [min, max]: {iti_range}")
    lo, hi = iti_range
    if lo < 0 or hi < lo:
        raise ValueError(f"{where} must satisfy 0 <= min <= max: {iti_range}")


def _build(cls, data: Any, where: str):
    """Construct a config dataclass from a JSON mapping, rejecting unknown keys.

    A misspelled key is the quietest kind of config error: the value is simply
    ignored and the session runs on the default, which is indistinguishable in
    the data from having meant the default all along.  Naming the offender at
    load time costs one set difference and removes the whole class of bug.
    """
    if not isinstance(data, dict):
        raise ValueError(f"{where} must be a JSON object, got {type(data).__name__}")
    known = {f.name for f in fields(cls)}
    unknown = sorted(set(data) - known)
    if unknown:
        raise ValueError(
            f"{where}: unknown key(s) {unknown}. Valid keys: {sorted(known)}"
        )
    return cls(**data)


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
    """Camera placement and the input → corridor velocity gain.

    ``speed_scaling`` converts the encoder's units into corridor units per
    second and applies to both hardware paths — ``serial`` (MousePortal owns
    the port) and ``network`` (mesofield owns it and forwards samples). It is
    the knob that sets how far the corridor travels per unit of treadmill
    motion, so it is what you calibrate against the animal's real running.

    ``keyboard_speed`` is the corridor speed while an arrow key is held. It is
    already expressed in corridor units per second, so ``speed_scaling`` does
    not apply to it — keyboard mode is for testing the corridor, not for
    reproducing a calibrated treadmill gain.
    """
    height: float = 2.0
    speed_scaling: float = 1.0     # encoder units → corridor units/s
    keyboard_speed: float = 20.0   # corridor units/s while an arrow key is held

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

    ``label`` and ``transform_type`` are required: a condition that does not
    say what it is has no defensible default, and inventing one is how a
    mislabelled trial reaches the CSV looking deliberate.

    Per-condition trial-end overrides
    ---------------------------------
    Trial end
    ---------
    Each condition states how its own trials end.  There is no session-wide
    end rule to fall back on: a rule and its limit belong together, and
    splitting them across two levels meant a condition's real behaviour could
    only be worked out by reading both.  ``duration`` requires
    ``trial_duration``; ``distance`` requires ``trial_distance``; ``manual``
    requires neither and ends on the experimenter's keypress.

    Per-condition ITI
    -----------------
    ``iti_after=False`` suppresses the interval after this condition, so
    the next condition in the sequence starts on the same frame — that is
    how several conditions are chained into one perceived trial.
    ``iti_range`` overrides the session's draw for the interval this
    condition ends with.
    """
    label: str
    transform_type: str
    trial_end_condition: TrialEndCondition
    transform_params: Dict[str, Any] = field(default_factory=dict)
    trial_distance: Optional[float] = None
    trial_duration: Optional[float] = None
    # Planning metadata, never read by the state machine: how long a trial of
    # this condition is expected to take when its end rule is one whose
    # duration cannot be known in advance (``distance``, ``manual``).  An
    # orchestrator sizing a recording needs a number for those trials, and an
    # explicit estimate is honest where a guessed one is not.
    expected_duration: Optional[float] = None
    iti_after: bool = True
    iti_range: Optional[Tuple[float, float]] = None
    # Future go/no-go fields (uncomment when needed):
    # wall_texture_override: Optional[str] = None
    # trigger_on_enter: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.label:
            raise ValueError("condition label must be a non-empty string")
        where = f"condition '{self.label}'"
        if not isinstance(self.trial_end_condition, TrialEndCondition):
            raise ValueError(
                f"{where}: trial_end_condition must be one of "
                f"{[e.value for e in TrialEndCondition]}, got "
                f"{self.trial_end_condition!r}"
            )

        if self.trial_end_condition is TrialEndCondition.DURATION:
            if not self.trial_duration or self.trial_duration <= 0:
                raise ValueError(
                    f"{where}: trial_end_condition 'duration' needs a positive "
                    f"trial_duration, got {self.trial_duration!r}"
                )
        elif self.trial_end_condition is TrialEndCondition.DISTANCE:
            if not self.trial_distance or self.trial_distance <= 0:
                raise ValueError(
                    f"{where}: trial_end_condition 'distance' needs a positive "
                    f"trial_distance, got {self.trial_distance!r}"
                )
            # An open-loop transform discards the subject's input, so a
            # distance rule either can never be satisfied (freeze) or is
            # satisfied by motion the subject did not produce (reverse). Both
            # read as an animal that will not run, hours into a session.
            if self.transform_type in _OPEN_LOOP_TRANSFORMS:
                raise ValueError(
                    f"{where}: transform '{self.transform_type}' ignores the "
                    f"subject's input, so a 'distance' end rule cannot be reached "
                    f"by the subject's running. Use 'duration' or 'manual'."
                )
        if self.expected_duration is not None and self.expected_duration <= 0:
            raise ValueError(
                f"{where}: expected_duration must be positive, got "
                f"{self.expected_duration!r}"
            )
        _check_iti_range(self.iti_range, f"{where}: iti_range")

    @property
    def planning_duration(self) -> Optional[float]:
        """Seconds a trial of this condition is expected to take, if knowable.

        A ``duration`` trial is its own estimate.  Otherwise this is whatever
        ``expected_duration`` says, and ``None`` when nothing says — a caller
        sizing a recording must decide what to do about that rather than be
        handed a number nobody stated.
        """
        if self.trial_end_condition is TrialEndCondition.DURATION:
            return self.trial_duration
        return self.expected_duration


class BlockOrder(str, Enum):
    """How a block's expanded trial sequence is ordered."""
    FIXED = "fixed"       # run the sequence exactly as written
    SHUFFLE = "shuffle"   # permute it with the session seed


@dataclass(frozen=True)
class BlockConfig:
    """One block: a trial sequence, optionally repeated and/or shuffled.

    ``sequence`` is the ordered list of condition labels making up one pass of
    the block.  ``repeat`` concatenates that many passes, so ``repeat`` never
    changes the *balance* of the block — three repeats of four conditions is
    always twelve trials, three of each.  ``order="shuffle"`` then permutes
    the expanded list with the session's seed, which keeps the counts exact
    while randomising presentation order.

    The block's trial count is therefore ``len(sequence) * repeat``.  There is
    no global trials-per-block: blocks are independent and may differ in
    length, which is what makes "one long training block, then two
    counterbalanced test blocks" expressible.

    ``name`` is optional and is carried into the events and trials tables, so
    analysis can group by a meaningful label rather than a block index.
    """
    sequence: Tuple[str, ...]
    name: str = ""
    repeat: int = 1
    order: BlockOrder = BlockOrder.FIXED

    def __post_init__(self) -> None:
        if not self.sequence:
            raise ValueError(f"block {self.describe()}: sequence must not be empty")
        if self.repeat < 1:
            raise ValueError(f"block {self.describe()}: repeat must be >= 1, got {self.repeat}")

    def describe(self) -> str:
        """Human handle for error messages: the name if it has one."""
        return f"'{self.name}'" if self.name else "(unnamed)"

    @property
    def num_trials(self) -> int:
        """Trials this block runs once expanded."""
        return len(self.sequence) * self.repeat

    def expand(self, rng: random.Random) -> List[str]:
        """The realised trial order for this block.

        ``rng`` is consumed only when ``order`` is ``shuffle``, so a fixed
        block's expansion is independent of the seed.
        """
        trials = list(self.sequence) * self.repeat
        if self.order is BlockOrder.SHUFFLE:
            rng.shuffle(trials)
        return trials


@dataclass(frozen=True)
class ExperimentConfig:
    """The session design: a palette of conditions and a list of blocks.

    ``blocks`` is the single source of truth for session structure — the
    number of blocks is ``len(blocks)`` and each block's trial count comes
    from its own sequence.  Nothing else declares those counts, so nothing
    else can disagree with them.

    Trial-end rules live on the conditions, not here.  A rule and its limit
    belong together, and a session-wide default that each condition may or may
    not override means the behaviour of a trial can only be read by consulting
    two places at once.

    Every condition label referenced by a block must exist in ``conditions``,
    and every condition's transform must build with its parameters.  Both are
    checked here, at load, rather than at the trial that first needs them.
    """
    conditions: Tuple[TrialCondition, ...] = ()
    blocks: Tuple[BlockConfig, ...] = ()
    iti_duration: float = 2.0
    # When set to (min, max), each ITI is drawn uniformly from that range with
    # the seeded RNG instead of using the fixed ``iti_duration``.
    iti_range: Optional[Tuple[float, float]] = None
    # Seed for every random draw in the session. Left as None, the state machine
    # falls back to today's date and records it in the timing sidecar.
    random_seed: Optional[int] = None

    def __post_init__(self) -> None:
        if self.iti_duration < 0:
            raise ValueError(f"iti_duration must be non-negative: {self.iti_duration}")
        _check_iti_range(self.iti_range, "iti_range")

        if not self.conditions:
            raise ValueError(
                "experiment.conditions must define at least one condition"
            )
        labels = [c.label for c in self.conditions]
        duplicates = sorted({lbl for lbl in labels if labels.count(lbl) > 1})
        if duplicates:
            raise ValueError(f"duplicate condition labels: {duplicates}")

        # Build every transform now so a bad parameter fails at startup rather
        # than mid-session, when the trial that needs it finally comes round.
        from mouseportal.transforms import build_transform
        for cond in self.conditions:
            try:
                build_transform(cond.transform_type, cond.transform_params or None)
            except (ValueError, TypeError) as exc:
                raise ValueError(f"condition '{cond.label}': {exc}") from None

        if not self.blocks:
            raise ValueError("experiment.blocks must define at least one block")
        known = set(labels)
        for i, blk in enumerate(self.blocks, start=1):
            unknown = [lbl for lbl in blk.sequence if lbl not in known]
            if unknown:
                raise ValueError(
                    f"block {i} {blk.describe()} references undefined condition(s) "
                    f"{sorted(set(unknown))}. Defined conditions: {sorted(known)}"
                )

    @property
    def num_blocks(self) -> int:
        """Number of blocks in the session."""
        return len(self.blocks)

    @property
    def total_trials(self) -> int:
        """Trials across the whole session, once every block is expanded."""
        return sum(blk.num_trials for blk in self.blocks)

    def condition_map(self) -> Dict[str, TrialCondition]:
        """Label → condition. Every block label is guaranteed to be a key."""
        return {c.label: c for c in self.conditions}

    def expand(self, rng: random.Random) -> List[List[str]]:
        """Realise every block's trial order, in session order."""
        return [blk.expand(rng) for blk in self.blocks]


@dataclass(frozen=True)
class TriggerConfig:
    enabled: bool = False
    port: str = ""
    baud_rate: int = 9600


@dataclass(frozen=True)
class TimingConfig:
    """How presentation time is measured.

    ``explicit_flip`` makes MousePortal call ``readyFlip()`` then
    ``flipFrame()`` itself in a task after ``igLoop``, bracketed by clock
    reads, instead of letting the swap happen at the start of the next frame's
    ``render_frame()``.  ``readyFlip`` forces a GPU sync (a one-pixel readback)
    so the measured swap is real; the cost is throughput.

    ``sync_video`` is applied as a PRC variable before the window opens, so it
    must be resolved from config before ``ShowBase`` is constructed.
    """
    explicit_flip: bool = True
    sync_video: bool = True
    dropped_frame_threshold: float = 1.5   # x the measured refresh interval

    def __post_init__(self) -> None:
        if self.dropped_frame_threshold <= 1.0:
            raise ValueError(
                f"dropped_frame_threshold must exceed 1.0: {self.dropped_frame_threshold}"
            )


@dataclass(frozen=True)
class SyncPatchConfig:
    """Photodiode patch geometry and levels.

    ``size`` is a fraction of the screen; ``high``/``low`` are luminances in
    [0, 1] and are what gets written to the ``sync_level`` column.
    """
    enabled: bool = False
    corner: str = "bottom-right"
    size: float = 0.08
    high: float = 1.0
    low: float = 0.0

    def __post_init__(self) -> None:
        if self.corner not in ("top-left", "top-right", "bottom-left", "bottom-right"):
            raise ValueError(f"sync_patch.corner must be a screen corner: {self.corner}")
        if not 0.0 < self.size <= 0.5:
            raise ValueError(f"sync_patch.size must be in (0, 0.5]: {self.size}")
        if not (0.0 <= self.low <= 1.0 and 0.0 <= self.high <= 1.0):
            raise ValueError(f"sync_patch levels must be in [0,1]: {self.low}, {self.high}")


@dataclass(frozen=True)
class AssetsConfig:
    """Where to look for corridor textures and models beyond the app install.

    ``model_path`` is appended to Panda3D's model search path, so texture and
    model references in :class:`CorridorConfig` resolve against it as well as
    against the working directory.  That lets a rig keep its stimulus assets
    outside the MousePortal checkout.
    """
    model_path: str = ""

    def __post_init__(self) -> None:
        # An asset directory that is not there resolves to silently missing
        # textures at render time, which reads as a corridor styling mistake
        # rather than a path one.
        if self.model_path:
            import os
            if not os.path.isdir(self.model_path):
                raise ValueError(
                    f"assets.model_path is not a directory: {self.model_path!r}"
                )


@dataclass(frozen=True)
class LoggingConfig:
    subject: str = ""     # e.g. "001"
    session: str = ""     # e.g. "01"
    task: str = ""        # e.g. "corridor"
    output_dir: str = "data"  # root output directory (standalone use)
    output_path: str = ""     # explicit output stem (overrides BIDS layout)

    def __post_init__(self) -> None:
        if not self.subject:
            raise ValueError("logging.subject must be set (e.g. '001')")
        if not self.session:
            raise ValueError("logging.session must be set (e.g. '01')")
        if not self.task:
            raise ValueError("logging.task must be set (e.g. 'corridor')")

    def stem(self) -> str:
        """
        Resolve the output path stem that all streams hang off.

        If ``output_path`` is set (an orchestrator such as mesofield owns path
        construction and hands MousePortal the location), it is used verbatim
        with any ``.csv`` suffix stripped — MousePortal does NOT build its own
        directory layout.  Otherwise a BIDS-style stem is built under
        ``output_dir`` for standalone use, e.g.
        ``data/sub-001/ses-01/beh/sub-001_ses-01_task-corridor_portal``.
        """
        if self.output_path:
            return self.output_path[:-4] if self.output_path.endswith(".csv") else self.output_path
        import os
        sub = f"sub-{self.subject}"
        ses = f"ses-{self.session}"
        beh_dir = os.path.join(self.output_dir, sub, ses, "beh")
        return os.path.join(beh_dir, f"{sub}_{ses}_task-{self.task}_portal")

    def stream_path(self, stream: str) -> str:
        """Path for one output stream: ``samples``, ``events``, ``trials``, ``timing``."""
        suffix = "json" if stream == "timing" else "csv"
        return f"{self.stem()}-{stream}.{suffix}"


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
    timing: TimingConfig = field(default_factory=TimingConfig)
    sync_patch: SyncPatchConfig = field(default_factory=SyncPatchConfig)
    assets: AssetsConfig = field(default_factory=AssetsConfig)

    # Sections that must be present: without them there is no experiment and
    # no place to write it, and a default for either would be a guess.
    _REQUIRED_SECTIONS = ("experiment", "logging")

    # ─── Loaders ────────────────────────────────────────────────────────
    @classmethod
    def from_json(cls, path: str) -> "PortalConfig":
        """
        Load and validate configuration from a JSON file.

        Raises on any I/O or validation error, naming the offending section —
        nothing is defaulted silently and no key is ignored.
        """
        try:
            with open(path, "r") as fh:
                raw: Dict[str, Any] = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Failed to load config '{path}': {exc}") from exc

        if not isinstance(raw, dict):
            raise ValueError(f"Config '{path}' must be a JSON object at the top level")

        known_sections = {f.name for f in fields(cls)}
        unknown = sorted(set(raw) - known_sections)
        if unknown:
            raise ValueError(
                f"Config '{path}': unknown section(s) {unknown}. "
                f"Valid sections: {sorted(known_sections)}"
            )
        missing = [s for s in cls._REQUIRED_SECTIONS if s not in raw]
        if missing:
            raise ValueError(f"Config '{path}' is missing required section(s): {missing}")

        return cls(
            window=_build(WindowConfig, raw.get("window", {}), "window"),
            corridor=_build(CorridorConfig, raw.get("corridor", {}), "corridor"),
            camera=_build(CameraConfig, raw.get("camera", {}), "camera"),
            fog=_build(FogConfig, _parse_fog(raw.get("fog", {})), "fog"),
            input=_build(InputConfig, _parse_input(raw.get("input", {})), "input"),
            experiment=_build(
                ExperimentConfig, _parse_experiment(raw["experiment"]), "experiment"
            ),
            triggers=_build(TriggerConfig, raw.get("triggers", {}), "triggers"),
            logging=_build(LoggingConfig, raw["logging"], "logging"),
            timing=_build(TimingConfig, raw.get("timing", {}), "timing"),
            sync_patch=_build(SyncPatchConfig, raw.get("sync_patch", {}), "sync_patch"),
            assets=_build(AssetsConfig, raw.get("assets", {}), "assets"),
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
    if not isinstance(d, dict):
        raise ValueError(f"experiment must be a JSON object, got {type(d).__name__}")
    out = dict(d)
    if "iti_range" in out and out["iti_range"] is not None:
        out["iti_range"] = tuple(out["iti_range"])
    if "conditions" in out:
        out["conditions"] = tuple(
            _build(TrialCondition, _parse_condition(c), f"experiment.conditions[{i}]")
            for i, c in enumerate(_as_list(out["conditions"], "experiment.conditions"))
        )
    if "blocks" in out:
        out["blocks"] = tuple(
            _build(BlockConfig, _parse_block(b, i), f"experiment.blocks[{i}]")
            for i, b in enumerate(_as_list(out["blocks"], "experiment.blocks"))
        )
    return out


def _parse_condition(d: Dict[str, Any]) -> Dict[str, Any]:
    """Convert condition JSON to TrialCondition kwargs."""
    if not isinstance(d, dict):
        raise ValueError(f"each condition must be a JSON object, got {type(d).__name__}")
    out = dict(d)
    label = out.get("label", "?")
    if "trial_end_condition" not in out:
        raise ValueError(
            f"condition '{label}' must state a trial_end_condition "
            f"({[e.value for e in TrialEndCondition]})"
        )
    out["trial_end_condition"] = _enum(
        TrialEndCondition, out["trial_end_condition"],
        f"condition '{label}': trial_end_condition",
    )
    if "iti_range" in out and out["iti_range"] is not None:
        out["iti_range"] = tuple(out["iti_range"])
    return out


def _parse_block(d: Dict[str, Any], index: int) -> Dict[str, Any]:
    """Convert block JSON to BlockConfig kwargs."""
    if not isinstance(d, dict):
        raise ValueError(
            f"experiment.blocks[{index}] must be a JSON object, got {type(d).__name__}"
        )
    out = dict(d)
    if "sequence" in out:
        out["sequence"] = tuple(
            _as_list(out["sequence"], f"experiment.blocks[{index}].sequence")
        )
    if "order" in out:
        out["order"] = _enum(
            BlockOrder, out["order"], f"experiment.blocks[{index}].order"
        )
    return out


def _as_list(value: Any, where: str) -> List[Any]:
    """Require a JSON array, so a bare string does not silently iterate as chars."""
    if not isinstance(value, list):
        raise ValueError(f"{where} must be a JSON array, got {type(value).__name__}")
    return value


def _enum(cls, value: Any, where: str):
    """Coerce a JSON string to *cls*, listing the valid values on failure."""
    try:
        return cls(value)
    except ValueError:
        raise ValueError(
            f"{where} must be one of {[e.value for e in cls]}, got {value!r}"
        ) from None
