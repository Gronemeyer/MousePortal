"""
MousePortal application — slim Panda3D orchestrator.

All domain logic lives in the other modules; this class wires them
together and runs a single, short ``update`` task each frame.
"""

from __future__ import annotations

from direct.showbase.ShowBase import ShowBase
from direct.task.Task import Task
from panda3d.core import TextNode, WindowProperties, LVecBase4f

from mouseportal.config import PortalConfig, TrialEndCondition
from mouseportal.corridor import Corridor
from mouseportal.datalog import DataLogger
from mouseportal.experiment import ExperimentState, ExperimentStateMachine
from mouseportal.fog import FogEffect
from mouseportal.input import InputManager
from mouseportal.triggers import TriggerManager


class MousePortal(ShowBase):
    """
    Main application for the infinite corridor stimulus.

    Construction sequence:
      1. Load & validate config (fail-fast).
      2. Set window properties.
      3. Create input manager (serial or keyboard).
      4. Build corridor geometry.
      5. Apply fog.
      6. Initialise experiment state machine.
      7. Initialise trigger manager.
      8. Open data logger.
      9. Register the single ``update`` task.
    """

    def __init__(self, config_path: str, autostart: bool = False) -> None:
        super().__init__()

        # ---- 1. Config ------------------------------------------------
        self.cfg = PortalConfig.from_json(config_path)
        self._autostart = autostart

        # ---- 2. Window ------------------------------------------------
        wp = WindowProperties()
        wp.setSize(self.cfg.window.width, self.cfg.window.height)
        self.win.requestProperties(wp)
        self.setFrameRateMeter(True)
        self.disableMouse()

        # ---- 3. Input -------------------------------------------------
        self.input = InputManager(
            self, self.cfg.input,
            speed_scaling=self.cfg.camera.speed_scaling,
            keyboard_speed=self.cfg.camera.keyboard_speed,
        )

        # ---- 4. Corridor geometry -------------------------------------
        self.corridor = Corridor(self, self.cfg.corridor)

        # ---- 5. Fog ---------------------------------------------------
        self.fog_effect = FogEffect(self, self.cfg.fog)

        # ---- 6. Experiment state machine ------------------------------
        self.experiment = ExperimentStateMachine(
            self.cfg.experiment,
            send_event=self._on_experiment_event,
        )

        # ---- 7. Triggers ----------------------------------------------
        self.triggers = TriggerManager(self.cfg.triggers)

        # ---- 8. Data logger -------------------------------------------
        log_path = self.cfg.logging.bids_path()
        self.data_logger = DataLogger(log_path)
        print(f"[MousePortal] Logging to: {log_path}")

        # ---- 9. Camera & update task ----------------------------------
        self._camera_position: float = 0.0
        self._distance_since_recycle: float = 0.0
        self.camera.setPos(0, 0, self.cfg.camera.height)
        self.camera.setHpr(0, 0, 0)

        self.accept("escape", self._shutdown)
        self.accept("space", self._on_space)
        self.accept("f1", self._toggle_debug_hud)

        # ---- Debug HUD (toggle with F1) ------------------------------
        self._debug_hud_on = True
        self._debug_root = self.aspect2d.attachNewNode("debug_hud_root")

        # -- Title bar --
        self._title_tn = TextNode("hud_title")
        self._title_tn.setAlign(TextNode.ALeft)
        self._title_tn.setTextColor(0.3, 0.9, 1.0, 1.0)       # cyan
        self._title_tn.setShadow(0.04, 0.04)
        self._title_tn.setShadowColor(0, 0, 0, 0.9)
        self._title_tn.setCardColor(0.05, 0.05, 0.1, 0.75)
        self._title_tn.setCardAsMargin(0.15, 0.15, 0.08, 0.08)
        self._title_tn.setCardDecal(True)
        self._title_np = self._debug_root.attachNewNode(self._title_tn)
        self._title_np.setScale(0.055)
        self._title_np.setPos(-1.35, 0, 0.95)

        # -- Main info panel --
        self._info_tn = TextNode("hud_info")
        self._info_tn.setAlign(TextNode.ALeft)
        self._info_tn.setTextColor(0.95, 0.92, 0.5, 1.0)      # warm yellow
        self._info_tn.setShadow(0.04, 0.04)
        self._info_tn.setShadowColor(0, 0, 0, 0.9)
        self._info_tn.setCardColor(0.05, 0.05, 0.1, 0.7)
        self._info_tn.setCardAsMargin(0.15, 0.15, 0.1, 0.1)
        self._info_tn.setCardDecal(True)
        self._info_np = self._debug_root.attachNewNode(self._info_tn)
        self._info_np.setScale(0.04)
        self._info_np.setPos(-1.35, 0, 0.85)

        # -- Keys footer --
        self._keys_tn = TextNode("hud_keys")
        self._keys_tn.setAlign(TextNode.ALeft)
        self._keys_tn.setTextColor(0.6, 0.6, 0.6, 0.85)       # dim gray
        self._keys_tn.setShadow(0.04, 0.04)
        self._keys_tn.setShadowColor(0, 0, 0, 0.7)
        self._keys_np = self._debug_root.attachNewNode(self._keys_tn)
        self._keys_np.setScale(0.035)
        self._keys_np.setPos(-1.35, 0, -0.92)
        self._keys_tn.setText(
            "[Space] start / end trial    [F1] toggle HUD    [Esc] quit"
        )

        self.taskMgr.add(self._update, "updateTask")

        # ---- 10. Autostart + readiness handshake ----------------------
        # When driven by an external orchestrator (e.g. mesofield), begin the
        # experiment immediately instead of waiting for a spacebar.
        if self._autostart:
            self.experiment.start()

        # Stdout handshake token: the parent process waits for this line to
        # know the corridor is up and accepting input (mirrors PsychoPy).
        print("MOUSEPORTAL_READY", flush=True)

    # ─── Core loop ──────────────────────────────────────────────────────────

    def _update(self, task: Task) -> int:
        """Per-frame update: input → experiment → move → recycle → log."""
        dt: float = globalClock.getDt()  # type: ignore[name-defined]

        # 1. Read velocity from the active input source.
        velocity: float = self.input.velocity

        # 2. Tick the experiment state machine.
        state = self.experiment.tick(dt, self._camera_position)

        # 3. Only move camera during TRIAL_RUNNING (or IDLE for free-run).
        move: float = 0.0
        effective_velocity: float = velocity
        if state in (ExperimentState.TRIAL_RUNNING, ExperimentState.IDLE, ExperimentState.INTER_TRIAL_INTERVAL):
            effective_velocity = self.experiment.apply_transform(
                velocity, dt, self._camera_position,
            )
            move = effective_velocity * dt
            self._camera_position += move
            self.camera.setY(self._camera_position)

        # 4. Recycle corridor segments.
        self._distance_since_recycle += move
        seg_len = self.corridor.segment_length
        while self._distance_since_recycle >= seg_len:
            self.corridor.recycle_forward()
            self._distance_since_recycle -= seg_len
        while self._distance_since_recycle <= -seg_len:
            self.corridor.recycle_backward()
            self._distance_since_recycle += seg_len

        # 5. Log.
        self.data_logger.log_frame(
            position=self._camera_position,
            velocity=velocity,
            effective_velocity=effective_velocity,
            condition=self.experiment.condition.label,
            state=state.name,
            block=self.experiment.block,
            trial=self.experiment.trial,
            treadmill_device_us=self.input.last_device_us,
        )

        # 6. Debug HUD.
        if self._debug_hud_on:
            fps = globalClock.getAverageFrameRate()  # type: ignore[name-defined]
            cond = self.experiment.condition
            exp = self.experiment
            ecfg = self.cfg.experiment

            # Title
            self._title_tn.setText(f"MousePortal  v{self._get_version()}")

            # Trial progress line
            progress = self._format_trial_progress(
                state, exp, ecfg, effective_velocity,
            )

            # Condition detail
            transform_info = cond.transform_type
            if cond.transform_params:
                params_str = "  ".join(
                    f"{k}={v}" for k, v in cond.transform_params.items()
                )
                transform_info += f"  ({params_str})"

            # Gain ratio (effective / raw) — shows the transform's effect
            if abs(velocity) > 0.001:
                gain_ratio = effective_velocity / velocity
                gain_str = f"{gain_ratio:+.2f}x"
            else:
                gain_str = "--"

            self._info_tn.setText(
                f"STATE       {state.name}\n"
                f"BLOCK       {exp.block} / {ecfg.num_blocks}"
                f"      TRIAL  {exp.trial} / {ecfg.trials_per_block}\n"
                f"CONDITION   {cond.label}"
                f"    TRANSFORM  {transform_info}\n"
                f"\n"
                f"POSITION    {self._camera_position:>10.2f}\n"
                f"RAW VEL     {velocity:>10.3f}\n"
                f"EFF VEL     {effective_velocity:>10.3f}"
                f"    GAIN  {gain_str}\n"
                f"\n"
                f"{progress}\n"
                f"\n"
                f"INPUT       {self.cfg.input.mode.value}"
                f"      END COND  {exp.active_end_condition.value}\n"
                f"FPS         {fps:.0f}"
            )

        return Task.cont

    # ─── Event handlers ─────────────────────────────────────────────────────

    def _on_experiment_event(self, event_name: str, details: dict) -> None:
        """Relay experiment state-transition events to the data log."""
        self.data_logger.log_event(event_name, details)

    def _on_space(self) -> None:
        """Space bar: start experiment or end current trial (manual mode)."""
        if self.experiment.state == ExperimentState.IDLE:
            self.experiment.start()
        elif self.experiment.state == ExperimentState.TRIAL_RUNNING:
            self.experiment.end_trial()

    def _toggle_debug_hud(self) -> None:
        """F1: toggle the on-screen debug overlay."""
        self._debug_hud_on = not self._debug_hud_on
        if self._debug_hud_on:
            self._debug_root.show()
        else:
            self._debug_root.hide()

    # ─── Debug HUD helpers ──────────────────────────────────────────────────

    @staticmethod
    def _get_version() -> str:
        try:
            from mouseportal._version import version
            return version
        except ImportError:
            return "dev"

    @staticmethod
    def _format_trial_progress(
        state: "ExperimentState",
        exp: "ExperimentStateMachine",
        ecfg: "object",
        effective_velocity: float,
    ) -> str:
        """Build a progress string with a text bar for the active phase."""
        bar_width = 20

        if state == ExperimentState.TRIAL_RUNNING:
            end_cond = exp.active_end_condition
            if end_cond == TrialEndCondition.DISTANCE:
                target = exp.active_trial_distance
                frac = min(exp.trial_distance / target, 1.0) if target > 0 else 0.0
                filled = int(frac * bar_width)
                bar = "|" + "=" * filled + "-" * (bar_width - filled) + "|"
                return (
                    f"TRIAL       {bar} {frac * 100:5.1f}%\n"
                    f"            {exp.trial_distance:.1f} / {target:.1f} dist"
                    f"   ({exp.trial_elapsed:.1f}s)"
                )
            elif end_cond == TrialEndCondition.DURATION:
                target = exp.active_trial_duration
                frac = min(exp.trial_elapsed / target, 1.0) if target > 0 else 0.0
                filled = int(frac * bar_width)
                bar = "|" + "=" * filled + "-" * (bar_width - filled) + "|"
                return (
                    f"TRIAL       {bar} {frac * 100:5.1f}%\n"
                    f"            {exp.trial_elapsed:.1f} / {target:.1f}s"
                )
            else:  # MANUAL
                return f"TRIAL       elapsed {exp.trial_elapsed:.1f}s   (manual end)"

        elif state == ExperimentState.INTER_TRIAL_INTERVAL:
            frac = min(exp.iti_elapsed / ecfg.iti_duration, 1.0) if ecfg.iti_duration > 0 else 0.0
            filled = int(frac * bar_width)
            bar = "|" + "." * filled + " " * (bar_width - filled) + "|"
            return f"ITI         {bar} {exp.iti_elapsed:.1f} / {ecfg.iti_duration:.1f}s"

        elif state == ExperimentState.IDLE:
            return "            Press [Space] to begin"

        elif state == ExperimentState.SESSION_COMPLETE:
            return "            Session complete"

        return ""

    def _shutdown(self) -> None:
        """Clean shutdown: close resources, then exit."""
        self.data_logger.close()
        self.input.close()
        self.triggers.close()
        self.userExit()


def main() -> None:
    """CLI entry point for the ``mouseportal`` command."""
    import argparse
    import json
    import sys
    from pathlib import Path

    parser = argparse.ArgumentParser(
        description="MousePortal infinite corridor stimulus",
    )
    parser.add_argument(
        "-c", "--config",
        default="cfg.json",
        help="Path to JSON configuration file (default: cfg.json)",
    )
    parser.add_argument(
        "--init",
        action="store_true",
        help="Write a default cfg.json to the current directory and exit",
    )
    parser.add_argument(
        "--autostart",
        action="store_true",
        help="Begin the experiment immediately instead of waiting for spacebar "
             "(used when launched by an external orchestrator such as mesofield)",
    )
    args = parser.parse_args()

    if args.init:
        dest = Path(args.config)
        if dest.exists():
            print(f"[MousePortal] '{dest}' already exists — not overwriting.", file=sys.stderr)
            sys.exit(1)
        dest.write_text(json.dumps(_DEFAULT_CONFIG, indent=4) + "\n")
        print(f"[MousePortal] Wrote default config to '{dest}'")
        return

    try:
        app = MousePortal(args.config, autostart=args.autostart)
    except (RuntimeError, ValueError) as exc:
        print(f"[MousePortal] startup error: {exc}", file=sys.stderr)
        sys.exit(1)

    app.run()


_DEFAULT_CONFIG: dict = {
    "window": {
        "width": 1920,
        "height": 1080,
    },
    "corridor": {
        "segment_length": 10.0,
        "corridor_width": 8.0,
        "wall_height": 10.0,
        "num_segments": 50,
        "left_wall_texture": "assets/test3.png",
        "right_wall_texture": "assets/test3.png",
        "floor_texture": "assets/black.png",
        "ceiling_texture": "assets/white.png",
    },
    "camera": {
        "height": 2.0,
        "speed_scaling": 0.05,
        "keyboard_speed": 20.0,
    },
    "fog": {
        "density": 0.06,
        "color": [0.5, 0.5, 0.5],
    },
    "input": {
        "mode": "keyboard",
        "serial_port": "/dev/ttyUSB0",
        "baud_rate": 57600,
    },
    "experiment": {
        "num_blocks": 2,
        "trials_per_block": 2,
        "iti_duration": 2.0,
        "trial_end_condition": "distance",
        "trial_distance": 50.0,
        "trial_duration": 60.0,
        "conditions": [
            {"label": "normal", "transform_type": "identity"},
        ],
        "block_conditions": [
            {"condition_sequence": ["normal", "normal"]},
        ],
    },
    "triggers": {
        "enabled": False,
        "port": "",
        "baud_rate": 9600,
    },
    "logging": {
        "subject": "001",
        "session": "01",
        "task": "corridor",
        "output_dir": "data",
    },
}
