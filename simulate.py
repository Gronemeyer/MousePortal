#!/usr/bin/env python3
"""
Headless simulation runner for the MousePortal glitch experiment.

Drives a synthetic "virtual mouse" through the full experiment protocol
(blocks, trials, conditions, transforms) without any Panda3D graphics.
Produces a CSV identical in format to a real session, suitable for
analysis and visualisation.

The virtual mouse uses an Ornstein–Uhlenbeck (mean-reverting) velocity
process that produces naturalistic locomotion: sustained running bouts
interspersed with brief pauses.

Usage
-----
    python simulate.py                      # use cfg.json
    python simulate.py -c my_experiment.json
    python simulate.py --fps 120 --seed 42  # higher frame rate, fixed seed

Output is written to data/sub-SIM/ses-SIM/beh/ by default.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

# ─── We only import the non-Panda3D modules from mouseportal. ───────────────
from mouseportal.config import (
    ExperimentConfig,
    LoggingConfig,
    PortalConfig,
    TrialCondition,
    TrialEndCondition,
)
from mouseportal.datalog import DataLogger
from mouseportal.experiment import ExperimentState, ExperimentStateMachine
from mouseportal.transforms import VelocityTransform, build_transform


# ── Synthetic locomotion model ────────────────────────────────────────────


@dataclass
class LocomotionParams:
    """Parameters for the Ornstein–Uhlenbeck velocity generator."""

    mean_speed: float = 18.0       # long-run mean (units / s)
    theta: float = 3.0             # reversion rate  (higher → snappier)
    sigma: float = 6.0             # diffusion noise (higher → jitterier)
    pause_prob: float = 0.002      # per-frame probability of entering a pause
    pause_dur_mean: float = 1    # mean pause duration (s)
    pause_dur_std: float = 3     # std-dev of pause duration (s)
    min_speed: float = 0.0         # clamp floor (no backward movement)


class VirtualMouse:
    """
    Generate a plausible velocity trace frame-by-frame.

    Between pauses, velocity follows an OU process:
        dv = θ (μ − v) dt  +  σ √dt ε      ε ~ N(0,1)

    Pauses are random bouts where velocity drops to zero.
    """

    def __init__(self, params: LocomotionParams | None = None) -> None:
        self.p = params or LocomotionParams()
        self._v: float = self.p.mean_speed
        self._pause_remaining: float = 0.0

    def step(self, dt: float) -> float:
        """Return the next velocity sample."""
        # --- check / update pause state ---
        if self._pause_remaining > 0:
            self._pause_remaining -= dt
            self._v = 0.0
            return 0.0

        if random.random() < self.p.pause_prob:
            dur = max(0.05, random.gauss(self.p.pause_dur_mean, self.p.pause_dur_std))
            self._pause_remaining = dur
            self._v = 0.0
            return 0.0

        # --- OU step ---
        dv = (
            self.p.theta * (self.p.mean_speed - self._v) * dt
            + self.p.sigma * math.sqrt(dt) * random.gauss(0, 1)
        )
        self._v += dv
        self._v = max(self.p.min_speed, self._v)
        return self._v


# ── Simulation engine ─────────────────────────────────────────────────────


def _load_experiment_config(config_path: str) -> Dict[str, Any]:
    """Load the full JSON and return the raw dict."""
    with open(config_path, "r") as fh:
        return json.load(fh)


def run_simulation(
    config_path: str,
    fps: float = 60.0,
    seed: int | None = None,
    output_dir: str | None = None,
    loco_params: LocomotionParams | None = None,
    verbose: bool = True,
) -> str:
    """
    Run the glitch experiment headlessly and return the CSV path.

    Parameters
    ----------
    config_path : str
        Path to cfg.json (or any MousePortal config file).
    fps : float
        Simulated frame rate (frames per second).
    seed : int | None
        RNG seed for reproducibility.
    output_dir : str | None
        Override the output directory (default: ``data``).
    loco_params : LocomotionParams | None
        Optional locomotion parameters for the virtual mouse.
    verbose : bool
        Print progress to stdout.

    Returns
    -------
    str
        Absolute path to the generated CSV file.
    """
    if seed is not None:
        random.seed(seed)

    # ── 1. Load config (only the experiment & logging sections matter) ──
    raw = _load_experiment_config(config_path)

    # Build a PortalConfig just for ExperimentConfig parsing.
    # We override some logging fields so output goes to a sim-specific path.
    log_raw = dict(raw.get("logging", {}))
    log_raw["subject"] = log_raw.get("subject", "SIM") + "-SIM"
    log_raw["session"] = log_raw.get("session", "SIM")
    log_raw["task"] = log_raw.get("task", "corridor") + "-sim"
    if output_dir:
        log_raw["output_dir"] = output_dir
    log_cfg = LoggingConfig(**log_raw)

    # Parse experiment config via the same helpers the real app uses.
    from mouseportal.config import _parse_experiment

    exp_cfg = ExperimentConfig(**_parse_experiment(raw.get("experiment", {})))

    # ── 2. Instantiate components ───────────────────────────────────────
    events_log: list[tuple[str, dict]] = []

    def capture_event(name: str, details: dict) -> None:
        events_log.append((name, details))

    esm = ExperimentStateMachine(exp_cfg, send_event=capture_event)

    csv_path = log_cfg.bids_path()
    logger = DataLogger(csv_path)

    mouse = VirtualMouse(loco_params)

    dt: float = 1.0 / fps
    position: float = 0.0
    frame: int = 0
    wall_clock_start = time.time()

    # Patch time.time so the DataLogger writes simulated timestamps
    # rather than real wall-clock time (the sim runs in milliseconds).
    _real_time = time.time
    _sim_epoch = _real_time()
    _sim_clock = [_sim_epoch]  # mutable container for closure

    def _fake_time() -> float:
        return _sim_clock[0]

    time.time = _fake_time

    if verbose:
        total_trials = exp_cfg.num_blocks * exp_cfg.trials_per_block
        print(f"[simulate] Config       : {config_path}")
        print(f"[simulate] FPS          : {fps}")
        print(f"[simulate] Seed         : {seed}")
        print(f"[simulate] Blocks       : {exp_cfg.num_blocks}")
        print(f"[simulate] Trials/block : {exp_cfg.trials_per_block}")
        print(f"[simulate] Total trials : {total_trials}")
        print(f"[simulate] Output       : {csv_path}")
        print()

    # ── 3. Start the experiment ─────────────────────────────────────────
    esm.start()

    # ── 4. Main simulation loop ─────────────────────────────────────────
    max_frames = int(fps * 3600)  # safety cap: 1 hour of simulated time

    while frame < max_frames:
        frame += 1
        _sim_clock[0] = _sim_epoch + frame * dt  # advance simulated clock

        # a) synthetic velocity
        raw_velocity = mouse.step(dt)

        # b) tick experiment
        state = esm.tick(dt, position)

        # c) apply transform & move
        effective_velocity = raw_velocity
        move = 0.0
        if state in (ExperimentState.TRIAL_RUNNING, ExperimentState.IDLE):
            effective_velocity = esm.apply_transform(raw_velocity, dt, position)
            move = effective_velocity * dt
            position += move

        # d) log frame
        logger.log_frame(
            position=position,
            velocity=raw_velocity,
            effective_velocity=effective_velocity,
            condition=esm.condition.label,
            state=state.name,
            block=esm.block,
            trial=esm.trial,
        )

        # e) flush any experiment events accumulated this frame
        for evt_name, evt_details in events_log:
            logger.log_event(evt_name, evt_details)
        events_log.clear()

        # f) progress
        if verbose and frame % int(fps * 5) == 0:
            sim_time = frame * dt
            print(
                f"  t={sim_time:7.1f}s  frame={frame:>7d}  "
                f"state={state.name:<25s}  "
                f"block={esm.block}  trial={esm.trial}  "
                f"pos={position:.1f}"
            )

        # g) stop when session is complete
        if state == ExperimentState.SESSION_COMPLETE:
            break

    # ── 5. Clean up ─────────────────────────────────────────────────────
    time.time = _real_time  # restore real time.time
    logger.close()
    wall_elapsed = _real_time() - wall_clock_start
    sim_time = frame * dt

    if verbose:
        print()
        print(f"[simulate] Done.")
        print(f"[simulate] Simulated time : {sim_time:.1f}s  ({frame} frames)")
        print(f"[simulate] Wall-clock     : {wall_elapsed:.2f}s")
        print(f"[simulate] CSV written to : {csv_path}")

    return csv_path


# ── CLI ───────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Headless simulation of a MousePortal glitch experiment",
    )
    parser.add_argument(
        "-c", "--config",
        default="cfg.json",
        help="Path to JSON config file (default: cfg.json)",
    )
    parser.add_argument(
        "--fps",
        type=float,
        default=60.0,
        help="Simulated frame rate in Hz (default: 60)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="RNG seed for reproducibility",
    )
    parser.add_argument(
        "-o", "--output-dir",
        default=None,
        help="Override output directory (default: from config)",
    )
    parser.add_argument(
        "--mean-speed",
        type=float,
        default=18.0,
        help="Mean locomotion speed of the virtual mouse (default: 18)",
    )
    parser.add_argument(
        "--sigma",
        type=float,
        default=8.0,
        help="Locomotion noise (OU diffusion sigma, default: 8)",
    )
    parser.add_argument(
        "-q", "--quiet",
        action="store_true",
        help="Suppress progress output",
    )
    args = parser.parse_args()

    loco = LocomotionParams(mean_speed=args.mean_speed, sigma=args.sigma)

    csv_path = run_simulation(
        config_path=args.config,
        fps=args.fps,
        seed=args.seed,
        output_dir=args.output_dir,
        loco_params=loco,
        verbose=not args.quiet,
    )


if __name__ == "__main__":
    main()
