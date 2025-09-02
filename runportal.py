#!/usr/bin/env python3
"""
Infinite Corridor using Panda3D

This script creates an infinite corridor effect with user-controlled forward/backward movement.

Features:
- Configurable parameters loaded from JSON
- Infinite corridor effect
- User-controlled movement
- [real-time] Data logging (timestamp, position, velocity)

The corridor consists of left, right, ceiling, and floor segments.
It uses the Panda3D CardMaker API to generate flat geometry for the corridor's four faces.
An infinite corridor/hallway effect is simulated by recycling the front segments to the back when the player moves forward. 


Configuration parameters are loaded from a JSON file "conf.json".

Author: Jacob Gronemeyer
Date: 2025-07-28
Version: 0.3
"""

import json
import sys
import csv
import os
import time
import serial
import threading
import queue
from typing import Any, Dict
from dataclasses import dataclass

from direct.showbase.ShowBase import ShowBase
from direct.task import Task
from panda3d.core import CardMaker, NodePath, Texture, WindowProperties, Fog, GraphicsPipe
from direct.showbase import DirectObject
from direct.fsm.FSM import FSM
from direct.gui.OnscreenText import OnscreenText
from panda3d.core import TextNode

# ─── Fix for running as subprocess ─────────────────────────────────────────────────────
# https://raw.githubusercontent.com/panda3d/panda3d/release/1.10.x/panda/src/doc/howto.use_config.txt
# https://stackoverflow.com/questions/73900341/what-is-the-path-of-config-prc-files-in-panda3d


# Configure Panda3D before any ShowBase initialization
from panda3d.core import loadPrcFileData
    
# Set essential graphics configuration
loadPrcFileData('', 'load-display pandagl')
loadPrcFileData('', 'aux-display pandadx9') 
loadPrcFileData('', 'aux-display pandadx8')
loadPrcFileData('', 'aux-display tinydisplay')
loadPrcFileData('', 'window-title MousePortal')

def load_config(config_file: str) -> Dict[str, Any]:
    """
    Load configuration parameters from a JSON file.
    
    Parameters:
        config_file (str): Path to the configuration file.
        
    Returns:
        dict: Configuration parameters.
    """
    try:
        with open(config_file, 'r') as f:
            config = json.load(f)
        return config
    except Exception as e:
        print(f"Error loading config file {config_file}: {e}")
        sys.exit(1)

class DataLogger:
    """
    Logs movement data to a CSV file.
    """
    def __init__(self, filename):
        """
        Initialize the data logger.
        
        Args:
            filename (str): Path to the CSV file.
        """
        self.filename = filename
        self.fieldnames = ['timestamp', 'position', 'velocity']
        file_exists = os.path.isfile(self.filename)
        self.file = open(self.filename, 'a', newline='')
        self.writer = csv.DictWriter(self.file, fieldnames=self.fieldnames)
        if not file_exists:
            self.writer.writeheader()

    def log(self, timestamp, position, velocity):
        self.writer.writerow({'timestamp': timestamp, 'position': position, 'velocity': velocity})
        self.file.flush()

    def close(self):
        self.file.close()

class EventLogger:
    """Save event markers with timing information."""

    def __init__(self, filename: str) -> None:
        self.filename = filename
        self.fieldnames = ["time_sent", "time_received", "delta", "position", "event_name"]
        file_exists = os.path.isfile(self.filename)
        self.file = open(self.filename, 'a', newline='')
        self.writer = csv.DictWriter(self.file, fieldnames=self.fieldnames)
        if not file_exists:
            self.writer.writeheader()

    def log(self, time_sent: float, time_received: float, position: float, name: str) -> None:
        delta = time_received - time_sent if time_sent is not None else None
        self.writer.writerow({
            'time_sent': time_sent,
            'time_received': time_received,
            'delta': delta,
            'position': position,
            'event_name': name,
        })
        self.file.flush()

    def close(self) -> None:
        self.file.close()
@dataclass
class EncoderData:
    """ Represents a single encoder reading."""
    timestamp: int
    distance: float
    speed: float

    def __repr__(self):
        return (f"EncoderData(timestamp={self.timestamp}, "
                f"distance={self.distance:.3f} mm, speed={self.speed:.3f} mm/s)")

class CommandListener:
    """Background thread to read commands from STDIN."""
    def __init__(self):
        self.queue = queue.Queue()
        self.thread = threading.Thread(target=self._reader, daemon=True)
        self.thread.start()

    def _reader(self):
        for line in sys.stdin:
            self.queue.put(line.strip())

    def get(self):
        try:
            return self.queue.get_nowait()
        except queue.Empty:
            return None

class ExperimentFSM(FSM):
    def __init__(self, owner):
        super().__init__("ExperimentFSM")
        self.owner = owner

    def enterIdle(self):
        self.owner.update_state_text("Idle")
        print("STATE IDLE")

    def enterRunning(self):
        self.owner.update_state_text("Running")
        print("STATE RUNNING")

    def exitRunning(self):
        self.owner.update_state_text("Idle")
        print("STATE STOPPED")



class Corridor:
    """
    Class for generating infinite corridor geometric rendering
    """
    def __init__(self, base: ShowBase, config: Dict[str, Any]) -> None:
        """
        Initialize the corridor by creating segments for each face.
        
        Parameters:
            base (ShowBase): The Panda3D base instance.
            config (dict): Configuration parameters.
        """
        self.base = base
        self.segment_length: float = config["segment_length"]
        self.corridor_width: float = config["corridor_width"]
        self.wall_height: float = config["wall_height"]
        self.num_segments: int = config["num_segments"]
        self.left_wall_texture: str = config["left_wall_texture"]
        self.right_wall_texture: str = config["right_wall_texture"]
        self.ceiling_texture: str = config["ceiling_texture"]
        self.floor_texture: str = config["floor_texture"]
        
        # Create a parent node for all corridor segments.
        self.parent: NodePath = base.render.attachNewNode("corridor")
        
        # Separate lists for each face.
        self.left_segments: list[NodePath] = []
        self.right_segments: list[NodePath] = []
        self.ceiling_segments: list[NodePath] = []
        self.floor_segments: list[NodePath] = []
        
        self.build_segments()
        
    def build_segments(self) -> None:
        """ 
        Build the initial corridor segments using CardMaker.
        """
        # two prerendered backward segments, then the forward segments
        hallway_segments = [-2, -1] + list(range(self.num_segments))

        for i in hallway_segments:
            segment_start: float = i * self.segment_length
            
            # ─── Left Wall ─────────────────────────────────────────────────────
            # Create a card with dimensions (segment_length x wall_height),
            # position it at x = -corridor_width/2 and rotate it so the face is inward.
            cm_left: CardMaker = CardMaker("left_wall")
            # The card is generated in the XY plane; here we use X (length) and Z (height).
            cm_left.setFrame(0, self.segment_length, 0, self.wall_height)
            left_node: NodePath = self.parent.attachNewNode(cm_left.generate())
            # Position the left wall at x = -corridor_width/2 and at the starting Y position
            left_node.setPos(-self.corridor_width / 2, segment_start, 0)
            # Rotate to face inward (rotate around Z axis by 90°)
            # This maps the card's original X (now wall height) to the Z axis and Y remains.
            left_node.setHpr(90, 0, 0)
            self.apply_texture(left_node, self.left_wall_texture)
            self.left_segments.append(left_node)
            
            # ─── Right Wall ─────────────────────────────────────────────────────
            cm_right: CardMaker = CardMaker("right_wall")
            cm_right.setFrame(0, self.segment_length, 0, self.wall_height)
            right_node: NodePath = self.parent.attachNewNode(cm_right.generate())
            right_node.setPos(self.corridor_width / 2, segment_start, 0)
            right_node.setHpr(-90, 0, 0) # Rotate to face inward (rotate around Z axis by -90°)
            self.apply_texture(right_node, self.right_wall_texture)
            self.right_segments.append(right_node)

            # ─── Ceiling (Top) ─────────────────────────────────────────────────
            cm_ceiling: CardMaker = CardMaker("ceiling")
            # The ceiling card covers the corridor width and one segment length.
            cm_ceiling.setFrame(-self.corridor_width / 2, self.corridor_width / 2, 0, self.segment_length)
            ceiling_node: NodePath = self.parent.attachNewNode(cm_ceiling.generate())
            ceiling_node.setPos(0, segment_start, self.wall_height)
            ceiling_node.setHpr(0, 90, 0)
            self.apply_texture(ceiling_node, self.ceiling_texture)
            self.ceiling_segments.append(ceiling_node)

            # ─── Floor (Bottom) ─────────────────────────────────────────────────
            cm_floor: CardMaker = CardMaker("floor")
            cm_floor.setFrame(-self.corridor_width / 2, self.corridor_width / 2, 0, self.segment_length)
            floor_node: NodePath = self.parent.attachNewNode(cm_floor.generate())
            floor_node.setPos(0, segment_start, 0)
            floor_node.setHpr(0, -90, 0)
            self.apply_texture(floor_node, self.floor_texture)
            self.floor_segments.append(floor_node)
            
    def apply_texture(self, node: NodePath, texture_path: str) -> None:
        texture: Texture = self.base.loader.loadTexture(texture_path)
        node.setTexture(texture)
        
    def set_texture(self, face: str, texture_path: str) -> None:
        lists = {
            "left": self.left_segments,
            "right": self.right_segments,
            "ceiling": self.ceiling_segments,
            "floor": self.floor_segments,
        }
        segs = lists.get(face.lower())
        if not segs:
            return
        texture = self.base.loader.loadTexture(texture_path)
        for seg in segs:
            seg.setTexture(texture)

    def recycle_segment(self, direction: str) -> None:
        """
        Recycle the front segments by repositioning them to the end of the corridor.
        This is called when the player has advanced by one segment length.
        """
        
        if direction == "forward":
            # Calculate new base Y position from the last segment in the left wall.
            new_y: float = self.left_segments[-1].getY() + self.segment_length
            # Recycle left wall segment.
            left_seg: NodePath = self.left_segments.pop(0)
            left_seg.setY(new_y)
            self.left_segments.append(left_seg)
            
            # Recycle right wall segment.
            right_seg: NodePath = self.right_segments.pop(0)
            right_seg.setY(new_y)
            self.right_segments.append(right_seg)
            
            # Recycle ceiling segment.
            ceiling_seg: NodePath = self.ceiling_segments.pop(0)
            ceiling_seg.setY(new_y)
            self.ceiling_segments.append(ceiling_seg)
            
            # Recycle floor segment.
            floor_seg: NodePath = self.floor_segments.pop(0)
            floor_seg.setY(new_y)
            self.floor_segments.append(floor_seg)

        elif direction == "backward":
            new_y = self.left_segments[0].getY() - self.segment_length
            # Recycle left wall segment.
            left_seg: NodePath = self.left_segments.pop(-1)
            left_seg.setY(new_y)
            self.left_segments.insert(0, left_seg)

            # Recycle right wall segment.
            right_seg: NodePath = self.right_segments.pop(-1)
            right_seg.setY(new_y)
            self.right_segments.insert(0, right_seg)

            # Recycle ceiling segment.
            ceiling_seg: NodePath = self.ceiling_segments.pop(-1)
            ceiling_seg.setY(new_y)
            self.ceiling_segments.insert(0, ceiling_seg)

            # Recycle floor segment.
            floor_seg: NodePath = self.floor_segments.pop(-1)
            floor_seg.setY(new_y)
            self.floor_segments.insert(0, floor_seg)
            
class FogEffect:
    """
    Parameters:
        base (ShowBase): The Panda3D base instance.
        fog_color (tuple): RGB color for the fog (default is white).
        near_distance (float): The near distance where the fog starts.
        far_distance (float): The far distance where the fog completely obscures the scene.
    """

    def __init__(self, base: ShowBase, fog_color, density):
        self.base = base
        self.fog = Fog("fog")
        base.setBackgroundColor(fog_color)
        
        # Set fog color.
        self.fog.setColor(*fog_color)
        
        # Set the density for the fog.
        self.fog.setExpDensity(density)
        
        # Attach the fog to the root node to affect the entire scene.
        render.setFog(self.fog)


class SerialInputManager(DirectObject.DirectObject):
    """
    This class abstracts the serial connection and starts a thread that listens
    for serial data.
    """
    def __init__(self, serial_port: str, baudrate: int = 57600, messenger: DirectObject = None) -> None:
        self._port = serial_port
        self._baud = baudrate
        try:
            self.serial = serial.Serial(self._port, self._baud, timeout=1)
        except serial.SerialException as e:
            print(f"{self.__class__}: I failed to open serial port {self._port}: {e}")
            raise
        self.accept('readSerial', self._store_data)
        self.data = EncoderData(0, 0.0, 0.0)
        self.messenger = messenger

    def _store_data(self, data: EncoderData):
        self.data = data

    def _read_serial(self, task: Task) -> Task:
        """Internal loop for continuously reading lines from the serial port."""
        # Read a line from the Teensy board
        raw_line = self.serial.readline()

        # Decode and strip newline characters
        line = raw_line.decode('utf-8', errors='replace').strip()
        if line:
            data = self._parse_line(line)
            if data:
                self.messenger.send("readSerial", [data])

        return Task.cont

    def _parse_line(self, line: str) -> EncoderData | None:
        """
        Expected line formats:
          - "timestamp,distance,speed"  or
          - "distance,speed"
        """
        parts = line.split(',')
        try:
            if len(parts) == 3:
                # Format: timestamp, distance, speed
                timestamp = int(parts[0].strip())
                distance = float(parts[1].strip())
                speed = float(parts[2].strip())
                return EncoderData(distance=distance, speed=speed, timestamp=timestamp)
            elif len(parts) == 2:
                # Format: distance, speed
                distance = float(parts[0].strip())
                speed = float(parts[1].strip())
                return EncoderData(distance=distance, speed=speed)
            else:
                # Likely a header or message line (non-data)
                return None
        except ValueError:
            # Non-numeric data (e.g., header info)
            return None

    
class DummyInputManager:
    """Stand-in for SerialInputManager when running without hardware."""
    def __init__(self):
        self.data = EncoderData(0, 0.0, 0.0)
    def _read_serial(self, task: Task) -> Task:
        return Task.cont


class MousePortal(ShowBase):
    """
    Main application class for Mouse Portal's infinite corridor.
    """
    def __init__(self, config_file, dev: bool = False) -> None:
        """
        Initialize the application, load configuration, set up the camera, user input,
        corridor geometry, and add the update task.
        """
        ShowBase.__init__(self)
        
        # Load configuration from JSON (direct option)
        # config: Dict[str, Any] = load_config("conf.json")
        # Load configuration (init option for testing)
        with open(config_file, 'r') as f:
            self.cfg: Dict[str, Any] = load_config(config_file)

        # ─── Window Properties ─────────────────────────────────────────────────────
        # Get the display width and height for both monitors
        pipe = self.win.getPipe()
        display_width = pipe.getDisplayWidth()
        display_height = pipe.getDisplayHeight()

        # Set window properties to span across both monitors
        wp: WindowProperties = WindowProperties()
        wp.setSize(1920 * 2, 1280)  # Double the width for two
        wp.set_origin(display_width, 0)
        self.dev = dev
        self.win.requestProperties(wp)
        self.setFrameRateMeter(True)
        # Disable default mouse-based camera control for mapped input
        self.disableMouse()
        
        # ─── Camera Setup ──────────────────────────────────────────────────────────
        self.camera_position: float = 0.0
        self.camera_velocity: float = 0.0
        self.speed_scaling: float = self.cfg.get("speed_scaling", 5.0)
        self.camera_height: float = self.cfg.get("camera_height", 2.0)  
        self.camera.setPos(0, self.camera_position, self.camera_height)
        self.camera.setHpr(0, 0, 0)
        
        # ─── User Input ────────────────────────────────────────────────────────────
        self.key_map: Dict[str, bool] = {"forward": False, "backward": False}
        self.accept("arrow_up", self.set_key, ["forward", True])
        self.accept("arrow_up-up", self.set_key, ["forward", False])
        self.accept("arrow_down", self.set_key, ["backward", True])
        self.accept("arrow_down-up", self.set_key, ["backward", False])
        self.accept('escape', self.userExit)

        # ─── Treadmill Input ─────────────────────────────────────────────────────
        if self.dev:
            self.treadmill = DummyInputManager()
        else:
            self.treadmill = SerialInputManager(serial_port=self.cfg["serial_port"], 
                                                messenger=self.messenger)

        # ─── Corridor Setup ─────────────────────────────────────────────────────
        self.corridor: Corridor = Corridor(self, self.cfg)
        self.segment_length: float = self.cfg["segment_length"]
        
        # Variable to track movement since last recycling.
        self.distance_since_recycle: float = 0.0
        
        # Movement speed (units per second).
        self.movement_speed: float = 10.0
        
        # ─── Fog Effect ─────────────────────────────────────────────────────────────
        self.fog_effect = FogEffect(self, 
                                    density= self.cfg["fog_density"], 
                                    fog_color=(0.5, 0.5, 0.5))
        
        # ─── Data and Event Logging ────────────────────────────────────────────────
        self.data_logger = DataLogger(self.cfg["data_logging_file"])
        self.event_logger = EventLogger(self.cfg.get("event_log_file", "event_markers.csv"))

        # ─── TaskMgr and FSM ──────────────────────────────────────────────────────
        self.taskMgr.add(self.update, "updateTask")
        self.command_listener = CommandListener()
        self.fsm = ExperimentFSM(self)
        self.fsm.request("Idle")
        if self.dev:
            self.state_text = OnscreenText(text="State: Idle", 
                                           pos=(-1.3, 0.9), 
                                           scale=0.07, 
                                           align=TextNode.ALeft)
        self.events = []
        self.taskMgr.add(self.process_commands, "commandTask")

        
        # self.taskMgr.setupTaskChain("serialInputDevice", numThreads = 1, tickClock = None,
        #                threadPriority = None, frameBudget = None,
        #                frameSync = True, timeslicePriority = None)
        if not self.dev:
            self.taskMgr.add(self.treadmill._read_serial, name="readSerial")

        if dev:
            # In development mode, enable verbose logging for debugging.
            self.messenger.toggleVerbose()
            self.accept("v", self.messenger.toggle_verbose)

    def userExit(self):
        self.data_logger.close()
        self.event_logger.close()
        super().userExit()

    def set_key(self, key: str, value: bool) -> None:
        self.key_map[key] = value
        
    def update_state_text(self, state: str):
        if self.dev and hasattr(self, "state_text"):
            self.state_text.setText(f"State: {state}")

    def update(self, task: Task) -> Task:
        """
        Update the camera's position based on user input and recycle corridor segments
        when the player moves forward beyond one segment.
        
        Parameters:
            task (Task): The Panda3D task instance.
            
        Returns:
            Task: Continuation signal for the task manager.
        """
        dt: float = globalClock.getDt()
        move_distance: float = 0.0
        
        if self.dev:
            if self.key_map["forward"]:
                self.camera_velocity = self.speed_scaling
            elif self.key_map["backward"]:
                self.camera_velocity = -self.speed_scaling
            else:
                self.camera_velocity = 0.0
        else:
            self.camera_velocity = self.treadmill.data.speed
        # Update camera position (movement along the Y axis)
        self.camera_position += self.camera_velocity * dt
        move_distance = self.camera_velocity * dt
        self.camera.setPos(0, self.camera_position, self.camera_height)
        
        # Recycle corridor segments when the camera moves beyond one segment length
        # ─── Forward Movement -----> ───────────────────────────────────────────────────
        # Recycle segments from the back to the front
        if move_distance > 0:
            self.distance_since_recycle += move_distance
            while self.distance_since_recycle >= self.segment_length:
                self.corridor.recycle_segment(direction="forward")
                self.distance_since_recycle -= self.segment_length
        # ─── Backward Movement <----- ──────────────────────────────────────────────────
        # Recycle segments from the front to the back
        elif move_distance < 0:
            self.distance_since_recycle += move_distance
            while self.distance_since_recycle <= -self.segment_length:
                self.corridor.recycle_segment(direction="backward")
                self.distance_since_recycle += self.segment_length
        
        # Log movement data (timestamp, position, velocity)
        self.data_logger.log(time.time(), self.camera_position, self.camera_velocity)
        
        print(f"STATUS {time.time()} {self.camera_position:.3f} {self.camera_velocity:.3f}")
        sys.stdout.flush()
        return Task.cont

    def process_commands(self, task: Task) -> Task:
        cmd = self.command_listener.get()
        if cmd:
            parts = cmd.split()
            if parts[0].lower() == 'start_trial':
                sent = float(parts[1]) if len(parts) > 1 else None
                self.mark_event('start_trial', sent)
                self.fsm.request('Running')
            elif parts[0].lower() == 'stop_trial':
                sent = float(parts[1]) if len(parts) > 1 else None
                self.mark_event('stop_trial', sent)
                self.fsm.request('Idle')
            elif parts[0].lower() == 'set_texture' and len(parts) >= 3:
                self.corridor.set_texture(parts[1], parts[2])
            elif parts[0].lower() == "end":
                self.userExit()
                return Task.done
            elif parts[0].lower() == 'mark_event':
                name = parts[1] if len(parts) > 1 else 'event'
                sent = float(parts[2]) if len(parts) > 2 else None
                self.mark_event(name, sent)
        return Task.cont

    def mark_event(self, name: str, sent_time: float | None = None):
        recv = time.time()
        delta = recv - sent_time if sent_time is not None else None
        self.events.append({'name': name, 'time_sent': sent_time, 'time_received': recv, 'position': self.camera_position, 'delta': delta})
        self.event_logger.log(sent_time, recv, self.camera_position, name)
        print(f'EVENT {name} {recv} {self.camera_position} {delta}')
        sys.stdout.flush()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--cfg", default="cfg.json")
    parser.add_argument("--dev", action="store_true", help="Run without hardware")
    args = parser.parse_args()
    app = MousePortal(args.cfg, dev=True)
    app.run()
