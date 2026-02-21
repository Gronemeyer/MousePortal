"""
MousePortal application — slim Panda3D orchestrator.

All domain logic lives in the other modules; this class wires them
together and runs a single, short ``update`` task each frame.
"""

from __future__ import annotations

from direct.showbase.ShowBase import ShowBase
from direct.task.Task import Task
from panda3d.core import TextNode, WindowProperties

from mouseportal.config import PortalConfig
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

    def __init__(self, config_path: str) -> None:
        super().__init__()

        # ---- 1. Config ------------------------------------------------
        self.cfg = PortalConfig.from_json(config_path)

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
        self._debug_text = TextNode("debug_hud")
        self._debug_text.setAlign(TextNode.ALeft)
        self._debug_text.setTextColor(1, 1, 0, 1)
        self._debug_text.setShadow(0.05, 0.05)
        self._debug_text.setShadowColor(0, 0, 0, 0.8)
        self._debug_np = self.aspect2d.attachNewNode(self._debug_text)
        self._debug_np.setScale(0.045)
        self._debug_np.setPos(-1.3, 0, 0.9)

        self.taskMgr.add(self._update, "updateTask")

    # ------------------------------------------------------------------
    # Core loop
    # ------------------------------------------------------------------

    def _update(self, task: Task) -> int:
        """Per-frame update: input → experiment → move → recycle → log."""
        dt: float = globalClock.getDt()  # type: ignore[name-defined]

        # 1. Read velocity from the active input source.
        velocity: float = self.input.velocity

        # 2. Tick the experiment state machine.
        state = self.experiment.tick(dt, self._camera_position)

        # 3. Only move camera during TRIAL_RUNNING (or IDLE for free-run).
        move: float = 0.0
        if state in (ExperimentState.TRIAL_RUNNING, ExperimentState.IDLE):
            move = velocity * dt
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
            state=state.name,
            block=self.experiment.block,
            trial=self.experiment.trial,
        )

        # 6. Debug HUD.
        if self._debug_hud_on:
            self._debug_text.setText(
                f"State: {state.name}\n"
                f"Block: {self.experiment.block}  Trial: {self.experiment.trial}\n"
                f"Pos: {self._camera_position:.2f}  Vel: {velocity:.3f}\n"
                f"Input: {self.cfg.input.mode.value}\n"
                f"[Space] start/end trial  [F1] toggle HUD  [Esc] quit"
            )

        return Task.cont

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

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
            self._debug_np.show()
        else:
            self._debug_np.hide()
            self._debug_text.setText("")

    def _shutdown(self) -> None:
        """Clean shutdown: close resources, then exit."""
        self.data_logger.close()
        self.input.close()
        self.triggers.close()
        self.userExit()
