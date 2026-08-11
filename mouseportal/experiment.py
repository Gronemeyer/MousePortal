"""
Block-based experiment state machine.

States
------
IDLE → (WAITING_FOR_TRIGGER) → BLOCK_START → TRIAL_RUNNING → INTER_TRIAL_INTERVAL
                                        ↓ (more trials)
                                    TRIAL_RUNNING
                                        ↓ (block done)
                                    BLOCK_END → (more blocks) → BLOCK_START
                                              → SESSION_COMPLETE

The state machine is advanced each frame via ``tick(dt, position)``.
Transitions emit named events through an injected callable so the logger and
trigger manager can react without tight coupling.

Event tokens are the experiment's vocabulary, not the state machine's internal
state names — ``TRIAL_START`` and ``TRIAL_END`` bracket a trial regardless of
which state follows.  The set is open: ``STIMULUS_ONSET``, ``RESPONSE`` and
``REWARD`` are reserved for paradigms that emit them.
"""

from __future__ import annotations

import json
from enum import Enum, auto
from typing import Any, Callable, Dict, Optional

from mouseportal.config import ExperimentConfig, TrialCondition, TrialEndCondition
from mouseportal.transforms import VelocityTransform, IdentityTransform, build_transform


class ExperimentState(Enum):
    """Possible states for the experiment controller."""
    IDLE = auto()
    WAITING_FOR_TRIGGER = auto()
    BLOCK_START = auto()
    TRIAL_RUNNING = auto()
    INTER_TRIAL_INTERVAL = auto()
    BLOCK_END = auto()
    SESSION_COMPLETE = auto()


class ExperimentStateMachine:
    """
    Drives the experiment through blocks and trials.

    Parameters
    ----------
    cfg : ExperimentConfig
        Experiment parameters (blocks, trials, ITI, end condition, …).
    send_event : callable
        ``send_event(event: str, fields: dict)`` — called for every event.
        ``fields`` carries ``block``, ``trial``, ``condition`` and ``value``.
    """

    def __init__(self, cfg: ExperimentConfig, send_event: Callable[..., None]) -> None:
        self.cfg = cfg
        self._send = send_event

        self.state: ExperimentState = ExperimentState.IDLE
        self.block: int = 0          # 1-indexed when running
        self.trial: int = 0          # 1-indexed within current block
        self._trial_elapsed: float = 0.0
        self._trial_distance_start: Optional[float] = None
        self._trial_distance_traveled: float = 0.0
        self._iti_elapsed: float = 0.0

        # Active trial condition & velocity transform
        self._condition: TrialCondition = TrialCondition()
        self._transform: VelocityTransform = IdentityTransform()

        # Resolved per-trial end parameters (condition override → global)
        self._active_end_condition: TrialEndCondition = cfg.trial_end_condition
        self._active_trial_distance: float = cfg.trial_distance
        self._active_trial_duration: float = cfg.trial_duration

    # ─── Public API ─────────────────────────────────────────────────────────

    def arm(self) -> None:
        """Hold in ``WAITING_FOR_TRIGGER`` until :meth:`start` is called.

        Distinct from ``IDLE``: idle is a free-run state where the corridor
        still tracks the treadmill, whereas an armed experiment is frozen
        waiting for the run's start trigger.  The wait is logged, so it is
        visible in the events table.
        """
        if self.state != ExperimentState.IDLE:
            return
        self.state = ExperimentState.WAITING_FOR_TRIGGER
        self._emit("SESSION_ARMED")

    def start(self) -> None:
        """Begin the first block (call once to kick off the session)."""
        if self.state not in (
            ExperimentState.IDLE,
            ExperimentState.WAITING_FOR_TRIGGER,
        ):
            return
        self.block = 0
        self._begin_next_block()

    def tick(self, dt: float, position: float) -> ExperimentState:
        """
        Advance the state machine by one frame.

        Parameters
        ----------
        dt : float
            Frame delta-time in seconds.
        position : float
            Current camera / corridor position (for distance-based trials).

        Returns
        -------
        ExperimentState
            The state *after* this tick (may have transitioned).
        """
        if self.state == ExperimentState.TRIAL_RUNNING:
            self._tick_trial(dt, position)
        elif self.state == ExperimentState.INTER_TRIAL_INTERVAL:
            self._tick_iti(dt)
        # IDLE, WAITING_FOR_TRIGGER, BLOCK_START, BLOCK_END, SESSION_COMPLETE:
        # no-op per frame
        return self.state

    @property
    def is_running(self) -> bool:
        """True when the corridor should be actively rendering movement."""
        return self.state == ExperimentState.TRIAL_RUNNING

    @property
    def condition(self) -> TrialCondition:
        """The active trial condition (label, transform info, …)."""
        return self._condition

    @property
    def trial_elapsed(self) -> float:
        """Seconds elapsed in the current trial."""
        return self._trial_elapsed

    @property
    def iti_elapsed(self) -> float:
        """Seconds elapsed in the current ITI."""
        return self._iti_elapsed

    @property
    def trial_distance(self) -> float:
        """Distance traveled since the current trial started."""
        return self._trial_distance_traveled

    @property
    def active_end_condition(self) -> TrialEndCondition:
        """The resolved end condition for the current trial."""
        return self._active_end_condition

    @property
    def active_trial_distance(self) -> float:
        """The resolved target distance for the current trial."""
        return self._active_trial_distance

    @property
    def active_trial_duration(self) -> float:
        """The resolved target duration for the current trial."""
        return self._active_trial_duration

    def apply_transform(self, velocity: float, dt: float, position: float) -> float:
        """Apply the active trial's velocity transform."""
        return self._transform(velocity, dt, position)

    # ─── Internals ──────────────────────────────────────────────────────────

    def _emit(self, event: str, value: Any = None, condition: Optional[str] = None) -> None:
        """Send one event. ``condition`` is left unset where it has no meaning."""
        self._send(event, {
            "block": self.block,
            "trial": self.trial,
            "condition": condition,
            "value": value,
        })

    def _begin_next_block(self) -> None:
        if self.block >= self.cfg.num_blocks:
            self.state = ExperimentState.SESSION_COMPLETE
            self._emit("SESSION_COMPLETE")
            return
        self.block += 1
        self.trial = 0
        self.state = ExperimentState.BLOCK_START
        self._emit("BLOCK_START")
        # Auto-advance to first trial immediately
        self._begin_next_trial()

    def _begin_next_trial(self) -> None:
        if self.trial >= self.cfg.trials_per_block:
            self.state = ExperimentState.BLOCK_END
            self._emit("BLOCK_END")
            self._begin_next_block()
            return
        self.trial += 1
        self._trial_elapsed = 0.0
        self._trial_distance_start = None  # latched on the trial's first tick
        self._trial_distance_traveled = 0.0

        # Look up the condition for this trial and build its transform.
        self._condition = self.cfg.condition_for(self.block, self.trial)
        self._transform = build_transform(
            self._condition.transform_type,
            self._condition.transform_params or None,
        )
        self._transform.reset()

        # Resolve per-trial end parameters (condition override → global).
        if self._condition.trial_end_condition is not None:
            self._active_end_condition = TrialEndCondition(self._condition.trial_end_condition)
        else:
            self._active_end_condition = self.cfg.trial_end_condition

        self._active_trial_distance = (
            self._condition.trial_distance
            if self._condition.trial_distance is not None
            else self.cfg.trial_distance
        )
        self._active_trial_duration = (
            self._condition.trial_duration
            if self._condition.trial_duration is not None
            else self.cfg.trial_duration
        )

        self.state = ExperimentState.TRIAL_RUNNING
        self._emit("TRIAL_START", condition=self._condition.label)

    def _tick_trial(self, dt: float, position: float) -> None:
        self._trial_elapsed += dt

        # Distance is tracked for every trial, not only distance-ended ones,
        # so the trial summary is comparable across end rules.
        if self._trial_distance_start is None:
            self._trial_distance_start = position
        self._trial_distance_traveled = abs(position - self._trial_distance_start)

        if self._active_end_condition == TrialEndCondition.DURATION:
            trial_over = self._trial_elapsed >= self._active_trial_duration
        elif self._active_end_condition == TrialEndCondition.DISTANCE:
            trial_over = self._trial_distance_traveled >= self._active_trial_distance
        else:
            trial_over = False  # MANUAL: the caller must invoke end_trial()

        if trial_over:
            self.end_trial()

    def _tick_iti(self, dt: float) -> None:
        self._iti_elapsed += dt
        if self._iti_elapsed >= self.cfg.iti_duration:
            self._begin_next_trial()

    # ─── External triggers ──────────────────────────────────────────────────

    def end_trial(self) -> None:
        """End the current trial (for MANUAL condition or abort)."""
        if self.state != ExperimentState.TRIAL_RUNNING:
            return
        self._emit(
            "TRIAL_END",
            value=self._active_end_condition.value,
            condition=self._condition.label,
        )
        if self.cfg.iti_duration > 0:
            self._iti_elapsed = 0.0
            self.state = ExperimentState.INTER_TRIAL_INTERVAL
            self._emit("ITI_START", condition=self._condition.label)
        else:
            self._begin_next_trial()

    def trial_summary(self) -> Dict[str, Any]:
        """The just-ended trial's facts, for the trials table."""
        return {
            "block": self.block,
            "trial": self.trial,
            "condition": self._condition.label,
            "transform": self._condition.transform_type,
            "transform_params": json.dumps(self._condition.transform_params or {}),
            "duration": self._trial_elapsed,
            "distance": self._trial_distance_traveled,
            "end_rule": self._active_end_condition.value,
        }
