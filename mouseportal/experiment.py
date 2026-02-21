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

from mouseportal.config import ExperimentConfig, TrialEndCondition

if TYPE_CHECKING:
    pass


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
        self._iti_elapsed: float = 0.0

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
        self._transition(ExperimentState.TRIAL_RUNNING)

    def _tick_trial(self, dt: float, position: float) -> None:
        self._trial_elapsed += dt

        trial_over = False
        if self.cfg.trial_end_condition == TrialEndCondition.DURATION:
            trial_over = self._trial_elapsed >= self.cfg.trial_duration
        elif self.cfg.trial_end_condition == TrialEndCondition.DISTANCE:
            if self._trial_distance_start == 0.0:
                self._trial_distance_start = position
            traveled = abs(position - self._trial_distance_start)
            trial_over = traveled >= self.cfg.trial_distance
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
