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

Session structure comes entirely from ``ExperimentConfig.blocks``: the number
of blocks is the length of that list and each block's trial count is the
length of its own expanded sequence, so blocks may differ in length and no
second declaration exists to contradict them.  The plan is expanded once at
construction — ``shuffle`` blocks are drawn there — which is what lets the
whole realised order be written to the timing sidecar before the first frame.

Event tokens are the experiment's vocabulary, not the state machine's internal
state names — ``TRIAL_START`` and ``TRIAL_END`` bracket a trial regardless of
which state follows.  The set is open: ``STIMULUS_ONSET``, ``RESPONSE`` and
``REWARD`` are reserved for paradigms that emit them.
"""

from __future__ import annotations

import json
import random
from enum import Enum, auto
from typing import Any, Callable, Dict, List, Optional

from mouseportal.config import (
    BlockConfig, ExperimentConfig, TrialCondition, TrialEndCondition,
    default_seed,
)
from mouseportal.transforms import VelocityTransform, IdentityTransform, build_transform


# Placeholder condition for the frames before the first trial starts. It is
# never looked up from the config and never runs a transform; it exists so
# ``condition`` is always a TrialCondition. Its label is deliberately not a
# plausible condition name — the previous default labelled every pre-session
# frame "normal", which is indistinguishable in the CSV from a real one.
_NO_CONDITION = TrialCondition(
    label="none",
    transform_type="identity",
    # Nothing ends this placeholder; MANUAL is the rule that never fires on
    # its own, which is the correct answer for "not in a trial".
    trial_end_condition=TrialEndCondition.MANUAL,
)


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

        # One seed for the whole session, exposed so the caller can record it;
        # passing it back reproduces the session exactly. An unset seed falls
        # back to today's date as YYYYMMDD, which is legible in the sidecar and
        # ties a session's random draws to the day it was run.
        self.seed: int = (
            cfg.random_seed if cfg.random_seed is not None else default_seed()
        )
        # Two independent streams derived from that one seed. Sharing a single
        # RNG would couple the two draws: adding a trial to a block would shift
        # every subsequent ITI, so two sessions that differ only in block
        # length would also differ in timing for no stated reason.
        _master = random.Random(self.seed)
        self._plan_rng = random.Random(_master.randrange(2 ** 31))
        self._rng = random.Random(_master.randrange(2 ** 31))

        # The realised trial order, resolved once here: shuffled blocks are
        # drawn now rather than at each block boundary, so the whole session's
        # plan can be recorded up front and replayed from the seed.
        self._plan: List[List[str]] = cfg.expand(self._plan_rng)
        self._conditions: Dict[str, TrialCondition] = cfg.condition_map()

        self._iti_target: float = cfg.iti_duration

        # Active trial condition & velocity transform. The end rule and its
        # limit come straight off the condition — there is nothing to resolve.
        self._condition: TrialCondition = _NO_CONDITION
        self._transform: VelocityTransform = IdentityTransform()

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
    def plan(self) -> List[List[str]]:
        """The realised trial order for every block, in session order.

        Resolved once at construction, so this is what the session *will* run
        (or did run), not what the config asked for — the difference being any
        ``shuffle`` block, whose order is drawn from the seed.
        """
        return [list(seq) for seq in self._plan]

    @property
    def num_blocks(self) -> int:
        """Blocks in the session."""
        return len(self._plan)

    @property
    def total_trials(self) -> int:
        """Trials across the whole session."""
        return sum(len(seq) for seq in self._plan)

    def describe_plan(self) -> Dict[str, Any]:
        """The session's realised design, for the timing sidecar.

        A ``shuffle`` block's order exists nowhere in the config — only in the
        seed — so recording the expanded sequence here is what makes a session
        readable without re-running the expansion to find out what happened.
        """
        return {
            "random_seed": self.seed,
            "total_trials": self.total_trials,
            "blocks": [
                {"name": blk.name, "order": blk.order.value, "sequence": seq}
                for blk, seq in zip(self.cfg.blocks, self._plan)
            ],
        }

    @property
    def block_config(self) -> BlockConfig:
        """The running block's config. Valid once :meth:`start` has been called."""
        return self.cfg.blocks[self.block - 1]

    @property
    def trials_in_block(self) -> int:
        """Trials in the running block. 0 before the session starts."""
        if not 1 <= self.block <= len(self._plan):
            return 0
        return len(self._plan[self.block - 1])

    @property
    def trial_elapsed(self) -> float:
        """Seconds elapsed in the current trial."""
        return self._trial_elapsed

    @property
    def iti_elapsed(self) -> float:
        """Seconds elapsed in the current ITI."""
        return self._iti_elapsed

    @property
    def iti_target(self) -> float:
        """Length drawn for the current ITI."""
        return self._iti_target

    @property
    def trial_distance(self) -> float:
        """Distance traveled since the current trial started."""
        return self._trial_distance_traveled

    @property
    def active_end_condition(self) -> TrialEndCondition:
        """The end rule for the current trial."""
        return self._condition.trial_end_condition

    @property
    def active_trial_distance(self) -> float:
        """The target distance for the current trial. 0 unless the rule is DISTANCE."""
        return self._condition.trial_distance or 0.0

    @property
    def active_trial_duration(self) -> float:
        """The target duration for the current trial. 0 unless the rule is DURATION."""
        return self._condition.trial_duration or 0.0

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
        if self.block >= len(self._plan):
            self.state = ExperimentState.SESSION_COMPLETE
            self._emit("SESSION_COMPLETE")
            return
        self.block += 1
        self.trial = 0
        self.state = ExperimentState.BLOCK_START
        # The block's name rides on the event's value, so the events table
        # identifies blocks by what they are and not only by their index.
        self._emit("BLOCK_START", value=self.block_config.name or None)
        # Auto-advance to first trial immediately
        self._begin_next_trial()

    def _begin_next_trial(self) -> None:
        sequence = self._plan[self.block - 1]
        if self.trial >= len(sequence):
            self.state = ExperimentState.BLOCK_END
            self._emit("BLOCK_END", value=self.block_config.name or None)
            self._begin_next_block()
            return
        self.trial += 1
        self._trial_elapsed = 0.0
        self._trial_distance_start = None  # latched on the trial's first tick
        self._trial_distance_traveled = 0.0

        # Look up the condition for this trial and build its transform. Every
        # label in the plan was checked against the palette at config load, so
        # a miss here is a bug in the plan, not bad input — hence no fallback.
        self._condition = self._conditions[sequence[self.trial - 1]]
        self._transform = build_transform(
            self._condition.transform_type,
            self._condition.transform_params or None,
        )
        self._transform.reset()

        self.state = ExperimentState.TRIAL_RUNNING
        self._emit("TRIAL_START", condition=self._condition.label)

    def _tick_trial(self, dt: float, position: float) -> None:
        self._trial_elapsed += dt

        # Distance is tracked for every trial, not only distance-ended ones,
        # so the trial summary is comparable across end rules.
        if self._trial_distance_start is None:
            self._trial_distance_start = position
        self._trial_distance_traveled = abs(position - self._trial_distance_start)

        if self.active_end_condition == TrialEndCondition.DURATION:
            trial_over = self._trial_elapsed >= self.active_trial_duration
        elif self.active_end_condition == TrialEndCondition.DISTANCE:
            trial_over = self._trial_distance_traveled >= self.active_trial_distance
        else:
            trial_over = False  # MANUAL: the caller must invoke end_trial()

        if trial_over:
            self.end_trial()

    def _tick_iti(self, dt: float) -> None:
        self._iti_elapsed += dt
        if self._iti_elapsed >= self._iti_target:
            self._begin_next_trial()

    def _draw_iti(self) -> float:
        """Length of the next ITI: a seeded uniform draw, or the fixed value.

        The just-ended condition owns the interval that follows it, so its
        ``iti_after`` / ``iti_range`` take precedence over the global values.
        """
        if not self._condition.iti_after:
            return 0.0
        iti_range = self._condition.iti_range or self.cfg.iti_range
        if iti_range is None:
            return self.cfg.iti_duration
        lo, hi = iti_range
        return self._rng.uniform(lo, hi)

    # ─── External triggers ──────────────────────────────────────────────────

    def end_trial(self) -> None:
        """End the current trial (for MANUAL condition or abort)."""
        if self.state != ExperimentState.TRIAL_RUNNING:
            return
        self._emit(
            "TRIAL_END",
            value=self.active_end_condition.value,
            condition=self._condition.label,
        )
        self._iti_target = self._draw_iti()
        if self._iti_target > 0:
            self._iti_elapsed = 0.0
            self.state = ExperimentState.INTER_TRIAL_INTERVAL
            # The corridor still tracks the treadmill during the ITI, but the
            # trial's transform ended with the trial — the ITI is closed-loop.
            self._transform = IdentityTransform()
            self._emit(
                "ITI_START", value=self._iti_target, condition=self._condition.label,
            )
        else:
            self._begin_next_trial()

    def trial_summary(self) -> Dict[str, Any]:
        """The just-ended trial's facts, for the trials table.

        ``block_name`` is omitted for an unnamed block rather than written as
        an empty string, so the CSV writer's ``n/a`` applies and a missing name
        reads the same as every other absent value in these tables.
        """
        summary: Dict[str, Any] = {
            "block": self.block,
            "trial": self.trial,
            "condition": self._condition.label,
            "transform": self._condition.transform_type,
            "transform_params": json.dumps(self._condition.transform_params or {}),
            "duration": self._trial_elapsed,
            "distance": self._trial_distance_traveled,
            "end_rule": self.active_end_condition.value,
        }
        if self.block_config.name:
            summary["block_name"] = self.block_config.name
        return summary
