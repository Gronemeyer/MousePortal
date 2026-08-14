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
from mouseportal.clock import FixedClock
from mouseportal.datalog import NA, SessionLogger
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
    Run the glitch experiment headlessly and return the output stem.

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
        Path stem the samples, events, trials and timing files hang off.
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

    # Parse experiment config via the same helpers the real app uses, so a
    # config the simulator accepts is one the app will accept too.
    from mouseportal.config import _build, _parse_experiment

    if "experiment" not in raw:
        raise ValueError(f"Config '{config_path}' is missing the 'experiment' section")
    exp_cfg = _build(ExperimentConfig, _parse_experiment(raw["experiment"]), "experiment")

    # ── 2. Instantiate components ───────────────────────────────────────
    events_log: list[tuple[str, dict]] = []

    def capture_event(name: str, fields: dict) -> None:
        events_log.append((name, fields))

    esm = ExperimentStateMachine(exp_cfg, send_event=capture_event)

    dt: float = 1.0 / fps
    wall_clock_start = time.time()
    clock = FixedClock(unix_start=wall_clock_start, dt=dt)

    stem = log_cfg.stem()
    logger = SessionLogger(
        stem,
        header={
            "clock": clock.describe(),
            "experiment": esm.describe_plan(),
            "display": {
                "sync_video": None,
                "explicit_flip": None,
                "dropped_frame_threshold": 1.5,
                "reported_refresh_hz": fps,
                "window_size": None,
            },
            "sync_patch": {"enabled": False},
            "software": {"panda3d": None, "mouseportal": "simulated"},
        },
        dropped_frame_threshold=1.5,
    )
    csv_path = f"{stem}-samples.csv"

    mouse = VirtualMouse(loco_params)

    position: float = 0.0
    frame: int = 0
    trial_start_ts: float = 0.0

    if verbose:
        print(f"[simulate] Config       : {config_path}")
        print(f"[simulate] FPS          : {fps}")
        print(f"[simulate] Seed         : {seed}")
        print(f"[simulate] Blocks       : {esm.num_blocks}")
        for i, (blk, seq) in enumerate(zip(exp_cfg.blocks, esm.plan), start=1):
            name = blk.name or f"block {i}"
            print(f"[simulate]   {name:<12}: {len(seq)} trials  [{', '.join(seq)}]")
        print(f"[simulate] Total trials : {esm.total_trials}")
        print(f"[simulate] Output       : {csv_path}")
        print()

    # ── 3. Start the experiment ─────────────────────────────────────────
    esm.start()

    # ── 4. Main simulation loop ─────────────────────────────────────────
    max_frames = int(fps * 3600)  # safety cap: 1 hour of simulated time

    while frame < max_frames:
        frame += 1
        clock.step()
        timestamp = clock.unix(clock.frame_time())

        # a) synthetic velocity
        raw_velocity = mouse.step(dt)

        # b) tick experiment
        state = esm.tick(dt, position)

        # c) apply transform & move — the same gate the live app uses
        effective_velocity = raw_velocity
        move = 0.0
        if state in (
            ExperimentState.TRIAL_RUNNING,
            ExperimentState.IDLE,
            ExperimentState.INTER_TRIAL_INTERVAL,
        ):
            effective_velocity = esm.apply_transform(raw_velocity, dt, position)
            move = effective_velocity * dt
            position += move

        # d) sample row. The simulated flip lands one frame period after the
        # frame starts, which is what a vsynced run without drops looks like.
        logger.write_sample({
            "frame": frame,
            "timestamp": timestamp,
            "flip_timestamp": timestamp + dt,
            "flip_wait": NA,
            "frame_dt": dt,
            "dropped": 0,
            "sync_level": NA,
            "state": state.name,
            "block": esm.block,
            "trial": esm.trial,
            "condition": esm.condition.label,
            "position": position,
            "velocity": raw_velocity,
            "effective_velocity": effective_velocity,
            "treadmill_device_us": NA,
            "treadmill_age": NA,
        })

        # e) flush this frame's events, and close out any trial that ended
        for evt_name, fields in events_log:
            logger.write_event({
                "timestamp": timestamp,
                "flip_timestamp": timestamp + dt,
                "frame": frame,
                "block": fields["block"],
                "trial": fields["trial"],
                "event": evt_name,
                "condition": fields["condition"] if fields["condition"] is not None else NA,
                "value": fields["value"] if fields["value"] is not None else NA,
            })
            if evt_name == "TRIAL_START":
                trial_start_ts = timestamp
            elif evt_name == "TRIAL_END":
                row = esm.trial_summary()
                row["start_timestamp"] = trial_start_ts
                row["end_timestamp"] = timestamp
                row["n_frames"] = logger.trial.n_frames
                row["n_dropped"] = logger.trial.n_dropped
                row["mean_velocity"] = logger.trial.mean_velocity
                row["mean_effective_velocity"] = logger.trial.mean_effective_velocity
                logger.write_trial(row)
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
    logger.close()
    wall_elapsed = time.time() - wall_clock_start
    sim_time = frame * dt

    if verbose:
        print()
        print(f"[simulate] Done.")
        print(f"[simulate] Simulated time : {sim_time:.1f}s  ({frame} frames)")
        print(f"[simulate] Wall-clock     : {wall_elapsed:.2f}s")
        print(f"[simulate] Written to     : {stem}-{{samples,events,trials}}.csv")

    return stem


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

    run_simulation(
        config_path=args.config,
        fps=args.fps,
        seed=args.seed,
        output_dir=args.output_dir,
        loco_params=loco,
        verbose=not args.quiet,
    )


if __name__ == "__main__":
    main()
