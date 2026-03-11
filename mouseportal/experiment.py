"""
Block-based experiment state machine.

States
------
IDLE → BLOCK_START → TRIAL_RUNNING → INTER_TRIAL_INTERVAL
                                        ↓ (more trials)
                                    TRIAL_RUNNING
                                        ↓ (block done)
                                    BLOCK_END → (more blocks) → BLOCK_START
                                              → SESSION_COMPLETE

The state machine is advanced each frame via ``tick(dt, position)``.
State transitions emit Panda3D messenger events so that the logger
and trigger manager can react without tight coupling.
"""

from __future__ import annotations

from enum import Enum, auto
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional

from mouseportal.config import ExperimentConfig, TrialCondition, TrialEndCondition
from mouseportal.transforms import VelocityTransform, IdentityTransform, build_transform


class ExperimentState(Enum):
    """Possible states for the experiment controller."""
    IDLE = auto()
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
        ``send_event(event_name: str, details: dict)`` — called on every
        state transition.  Typically wired to the Panda3D messenger or
        the DataLogger.
    """

    def __init__(self, cfg: ExperimentConfig, send_event: Callable[..., None]) -> None:
        self.cfg = cfg
        self._send = send_event

        self.state: ExperimentState = ExperimentState.IDLE
        self.block: int = 0          # 1-indexed when running
        self.trial: int = 0          # 1-indexed within current block
        self._trial_elapsed: float = 0.0
        self._trial_distance_start: float = 0.0
        self._trial_distance_traveled: float = 0.0
        self._iti_elapsed: float = 0.0

        # Active trial condition & velocity transform
        self._condition: TrialCondition = TrialCondition()
        self._transform: VelocityTransform = IdentityTransform()

        # Resolved per-trial end parameters (condition override → global)
        self._active_end_condition: TrialEndCondition = cfg.trial_end_condition
        self._active_trial_distance: float = cfg.trial_distance
        self._active_trial_duration: float = cfg.trial_duration

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Begin the first block (call once to kick off the session)."""
        if self.state != ExperimentState.IDLE:
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
        # IDLE, BLOCK_START, BLOCK_END, SESSION_COMPLETE: no-op per frame
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

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _transition(self, new_state: ExperimentState, **details: Any) -> None:
        old = self.state
        self.state = new_state
        event_info: Dict[str, Any] = {
            "from": old.name,
            "to": new_state.name,
            "block": self.block,
            "trial": self.trial,
        }
        event_info.update(details)
        self._send(f"experiment.{new_state.name}", event_info)

    def _begin_next_block(self) -> None:
        self.block += 1
        if self.block > self.cfg.num_blocks:
            self._transition(ExperimentState.SESSION_COMPLETE)
            return
        self.trial = 0
        self._transition(ExperimentState.BLOCK_START)
        # Auto-advance to first trial immediately
        self._begin_next_trial()

    def _begin_next_trial(self) -> None:
        self.trial += 1
        if self.trial > self.cfg.trials_per_block:
            self._transition(ExperimentState.BLOCK_END)
            self._begin_next_block()
            return
        self._trial_elapsed = 0.0
        self._trial_distance_start = 0.0  # caller passes absolute position
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

        self._transition(
            ExperimentState.TRIAL_RUNNING,
            condition=self._condition.label,
            transform=self._condition.transform_type,
        )

    def _tick_trial(self, dt: float, position: float) -> None:
        self._trial_elapsed += dt

        trial_over = False
        if self._active_end_condition == TrialEndCondition.DURATION:
            trial_over = self._trial_elapsed >= self._active_trial_duration
        elif self._active_end_condition == TrialEndCondition.DISTANCE:
            if self._trial_distance_start == 0.0:
                self._trial_distance_start = position
            traveled = abs(position - self._trial_distance_start)
            self._trial_distance_traveled = traveled
            trial_over = traveled >= self._active_trial_distance
        # MANUAL: trial_over stays False; caller must invoke end_trial()

        if trial_over:
            self.end_trial()

    def _tick_iti(self, dt: float) -> None:
        self._iti_elapsed += dt
        if self._iti_elapsed >= self.cfg.iti_duration:
            self._begin_next_trial()

    # ------------------------------------------------------------------
    # External triggers
    # ------------------------------------------------------------------

    def end_trial(self) -> None:
        """Manually end the current trial (for MANUAL condition or abort)."""
        if self.state != ExperimentState.TRIAL_RUNNING:
            return
        if self.cfg.iti_duration > 0:
            self._iti_elapsed = 0.0
            self._transition(ExperimentState.INTER_TRIAL_INTERVAL)
        else:
            self._begin_next_trial()
