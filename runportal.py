#!/usr/bin/env python3
"""
Infinite Corridor using Panda3D

This script creates an infinite corridor effect with user-controlled forward/backward movement.

Features:
- Configurable parameters loaded from JSON
- Infinite corridor effect
- User-controlled movement
- [real-time] Data logging (timestamp, distance, speed)

The corridor consists of left, right, ceiling, and floor segments.
It uses the Panda3D CardMaker API to generate flat geometry for the corridor's four faces.
An infinite corridor/hallway effect is simulated by recycling the front segments to the back when the player moves forward. 


Configuration parameters are loaded from a JSON file "conf.json".

Author: Jake Gronemeyer
Date: 2025-02-23
Version: 0.2
"""

import json
import sys
import csv
import os
import time
import serial
import random
from typing import Any, Dict
from dataclasses import dataclass

from direct.showbase.ShowBase import ShowBase
from direct.task import Task
from panda3d.core import CardMaker, NodePath, Texture, WindowProperties, Fog
from direct.showbase import DirectObject


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

@dataclass
class EncoderData:
    """ Represents a single encoder reading."""
    timestamp: int
    distance: float
    speed: float

    def __repr__(self):
        return (f"EncoderData(timestamp={self.timestamp}, "
                f"distance={self.distance:.3f} mm, speed={self.speed:.3f} mm/s)")

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
        self.fieldnames = ['timestamp', 'distance', 'speed']
        file_exists = os.path.isfile(self.filename)
        self.file = open(self.filename, 'a', newline='')
        self.writer = csv.DictWriter(self.file, fieldnames=self.fieldnames)
        if not file_exists:
            self.writer.writeheader()

    def log(self, data: EncoderData):
        self.writer.writerow({'timestamp': data.timestamp, 'distance': data.distance, 'speed': data.speed})
        self.file.flush()

    def close(self):
        self.file.close()


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
        self.special_wall: str = config["special_wall"]
        
        # Create a parent node for all corridor segments.
        self.parent: NodePath = base.render.attachNewNode("corridor")
        
        # Separate lists for each face.
        self.left_segments: list[NodePath] = []
        self.right_segments: list[NodePath] = []
        self.ceiling_segments: list[NodePath] = []
        self.floor_segments: list[NodePath] = []
        
        self.build_segments()
        
        # Add a task to change textures at a random interval.
        self.schedule_texture_change()

    def build_segments(self) -> None:
        """ 
        Build the initial corridor segments using CardMaker.
        """
        for i in range(self.num_segments):
            segment_start: float = i * self.segment_length
            
            # ==== Left Wall:
            # Create a card with dimensions (segment_length x wall_height),
            # position it at x = -corridor_width/2 and rotate it so the face is inward.
            cm_left: CardMaker = CardMaker("left_wall")
            # The card is generated in the XY plane; here we use X (length) and Z (height).
            cm_left.setFrame(0, self.segment_length, 0, self.wall_height)
            left_node: NodePath = self.parent.attachNewNode(cm_left.generate())
            # Position the left wall at x = -corridor_width/2 and at the starting Y position
            left_node.setPos(-self.corridor_width / 2, segment_start, 0)
            # Rotate to face inward (rotate around Z axis by 90°)
            left_node.setHpr(90, 0, 0)
            self.apply_texture(left_node, self.left_wall_texture)
            self.left_segments.append(left_node)
            
            # ==== Right Wall:
            cm_right: CardMaker = CardMaker("right_wall")
            cm_right.setFrame(0, self.segment_length, 0, self.wall_height)
            right_node: NodePath = self.parent.attachNewNode(cm_right.generate())
            right_node.setPos(self.corridor_width / 2, segment_start, 0)
            right_node.setHpr(-90, 0, 0) # Rotate to face inward (rotate around Z axis by -90°)
            self.apply_texture(right_node, self.right_wall_texture)
            self.right_segments.append(right_node)
            
            # ==== Ceiling (Top):
            cm_ceiling: CardMaker = CardMaker("ceiling")
            # The ceiling card covers the corridor width and one segment length.
            cm_ceiling.setFrame(-self.corridor_width / 2, self.corridor_width / 2, 0, self.segment_length)
            ceiling_node: NodePath = self.parent.attachNewNode(cm_ceiling.generate())
            ceiling_node.setPos(0, segment_start, self.wall_height)
            ceiling_node.setHpr(0, 90, 0)
            self.apply_texture(ceiling_node, self.ceiling_texture)
            self.ceiling_segments.append(ceiling_node)
            
            # ==== Floor (Bottom):
            cm_floor: CardMaker = CardMaker("floor")
            cm_floor.setFrame(-self.corridor_width / 2, self.corridor_width / 2, 0, self.segment_length)
            floor_node: NodePath = self.parent.attachNewNode(cm_floor.generate())
            floor_node.setPos(0, segment_start, 0)
            floor_node.setHpr(0, -90, 0)
            self.apply_texture(floor_node, self.floor_texture)
            self.floor_segments.append(floor_node)
            
    def apply_texture(self, node: NodePath, texture_path: str) -> None:
        """
        Load and apply the texture to a geometry node.
        
        Parameters:
            node (NodePath): The node to which the texture will be applied.
        """
        texture: Texture = self.base.loader.loadTexture(texture_path)
        node.setTexture(texture)
        
    def recycle_segment(self, direction: str) -> None:
        """
        Recycle the front segments by repositioning them to the end of the corridor.
        This is called when the player has advanced by one segment length.
        """
        # Calculate new base Y position from the last segment in the left wall.
        new_y: float = self.left_segments[-1].getY() + self.segment_length
        
        if direction == "forward":
            new_y = self.left_segments[-1].getY() + self.segment_length
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
            # Recycle two left wall segments.
            left_seg1: NodePath = self.left_segments.pop(-1)
            left_seg1.setY(new_y)
            self.left_segments.insert(0, left_seg1)
            
            left_seg2: NodePath = self.left_segments.pop(-1)
            left_seg2.setY(new_y - self.segment_length)  # Adjust the Y for the second segment.
            self.left_segments.insert(0, left_seg2)

            # Recycle two right wall segments.
            right_seg1: NodePath = self.right_segments.pop(-1)
            right_seg1.setY(new_y)
            self.right_segments.insert(0, right_seg1)
            
            right_seg2: NodePath = self.right_segments.pop(-1)
            right_seg2.setY(new_y - self.segment_length)  # Adjust the Y for the second segment.
            self.right_segments.insert(0, right_seg2)

            # Recycle two ceiling segments.
            ceiling_seg1: NodePath = self.ceiling_segments.pop(-1)
            ceiling_seg1.setY(new_y)
            self.ceiling_segments.insert(0, ceiling_seg1)
            
            ceiling_seg2: NodePath = self.ceiling_segments.pop(-1)
            ceiling_seg2.setY(new_y - self.segment_length)  # Adjust the Y for the second segment.
            self.ceiling_segments.insert(0, ceiling_seg2)

            # Recycle two floor segments.
            floor_seg1: NodePath = self.floor_segments.pop(-1)
            floor_seg1.setY(new_y)
            self.floor_segments.insert(0, floor_seg1)
            
            floor_seg2: NodePath = self.floor_segments.pop(-1)
            floor_seg2.setY(new_y - self.segment_length)  # Adjust the Y for the second segment.
            self.floor_segments.insert(0, floor_seg2)
            
    def change_wall_textures(self, task: Task = None) -> Task:
        """
        Change the textures of the left and right walls.
        
        Parameters:
            task (Task): The Panda3D task instance (optional).
            
        Returns:
            Task: Continuation signal for the task manager.
        """
        # Apply the new textures to the walls
        for left_node in self.left_segments:
            self.apply_texture(left_node, self.special_wall)
        for right_node in self.right_segments:
            self.apply_texture(right_node, self.special_wall)
            
        # Schedule the task to revert the textures after 5 seconds
        self.base.taskMgr.doMethodLater(5, self.revert_wall_textures, "revertWallTexturesTask")
        
        # Return Task.done if task is None
        return Task.done if task is None else task.done

    def revert_wall_textures(self, task: Task = None) -> Task:
        """
        Revert the textures of the left and right walls to their original textures.
        
        Parameters:
            task (Task): The Panda3D task instance (optional).
            
        Returns:
            Task: Continuation signal for the task manager.
        """
        # Reapply the original textures to the walls
        for left_node in self.left_segments:
            self.apply_texture(left_node, self.left_wall_texture)
        for right_node in self.right_segments:
            self.apply_texture(right_node, self.right_wall_texture)
            
        # Schedule the next texture change
        self.schedule_texture_change()
        
        # Return Task.done if task is None
        return Task.done if task is None else task.done

    def schedule_texture_change(self) -> None:
        """
        Schedule the next texture change after a random number of wall segments (between 3 and 10) are recycled.
        """
        # Randomly determine the number of segments after which to change the texture
        segments_to_wait = random.randint(10, 35)
        self.segments_until_texture_change = segments_to_wait

    def update_texture_change(self) -> None:
        """
        Check if the required number of segments has been recycled and change the texture if needed.
        """
        if self.segments_until_texture_change <= 0:
            self.change_wall_textures(None)  # Trigger the texture change
            self.schedule_texture_change()  # Schedule the next texture change
            
class FogEffect:
    """
    Class to manage and apply fog to the scene.
    """
    def __init__(self, base: ShowBase, fog_color, density):
        """
        Initialize the fog effect.
        
        Parameters:
            base (ShowBase): The Panda3D base instance.
            fog_color (tuple): RGB color for the fog (default is white).
            near_distance (float): The near distance where the fog starts.
            far_distance (float): The far distance where the fog completely obscures the scene.
        """
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
    Manages serial input via the pyserial interface.
    
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

    def _parse_line(self, line: str):
        """
        Parse a line of serial output.

        Expected line formats:
          - "timestamp,distance,speed"  or
          - "distance,speed"

        Args:
            line (str): A single line from the serial port.

        Returns:
            EncoderData: An instance with parsed values, or None if parsing fails.
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

    

class MousePortal(ShowBase):
    """
    Main application class for the infinite corridor simulation.
    """
    def __init__(self, config_file) -> None:
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

        # Set window properties
        wp = WindowProperties()
        wp.setSize(self.cfg["window_width"], self.cfg["window_height"])
        self.setFrameRateMeter(False)
        # Disable default mouse-based camera control for mapped input
        self.disableMouse()
        wp.setCursorHidden(True)
        wp.setFullscreen(True)
        wp.setUndecorated(True)
        self.win.requestProperties(wp)
        
        # Initialize camera parameters
        self.camera_position: float = 0.0
        self.camera_velocity: float = 0.0
        self.speed_scaling: float = self.cfg.get("speed_scaling", 5.0)
        self.camera_height: float = self.cfg.get("camera_height", 2.0)  
        self.camera.setPos(0, self.camera_position, self.camera_height)
        self.camera.setHpr(0, 0, 0)
        
        # Set up key mapping for keyboard input
        self.key_map: Dict[str, bool] = {"forward": False, "backward": False}
        self.accept("arrow_up", self.set_key, ["forward", True])
        self.accept("arrow_up-up", self.set_key, ["forward", False])
        self.accept("arrow_down", self.set_key, ["backward", True])
        self.accept("arrow_down-up", self.set_key, ["backward", False])
        self.accept('escape', self.userExit)

        # Set up treadmill input
        self.treadmill = SerialInputManager(serial_port = self.cfg["serial_port"], messenger = self.messenger)   

        # Create corridor geometry.
        self.corridor: Corridor = Corridor(self, self.cfg)
        self.segment_length: float = self.cfg["segment_length"]
        
        # Variable to track movement since last recycling.
        self.distance_since_recycle: float = 0.0
        
        # Movement speed (units per second).
        self.movement_speed: float = 10.0
        
        # Initialize data logger
        self.data_logger = DataLogger(self.cfg["data_logging_file"])

        # Add the update task.
        self.taskMgr.add(self.update, "updateTask")
        
     # Initialize fog effect
        self.fog_effect = FogEffect(self, density= self.cfg["fog_density"], fog_color=(0.5, 0.5, 0.5))
        
        # self.taskMgr.setupTaskChain("serialInputDevice", numThreads = 1, tickClock = None,
        #                threadPriority = None, frameBudget = None,
        #                frameSync = True, timeslicePriority = None)
        self.taskMgr.add(self.treadmill._read_serial, name = "readSerial")

        self.messenger.toggleVerbose()



    def set_key(self, key: str, value: bool) -> None:
        """
        Update the key state for the given key.
        
        Parameters:
            key (str): The key identifier.
            value (bool): True if pressed, False if released.
        """
        self.key_map[key] = value
        
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
        
        # Update camera velocity based on key input
        if self.key_map["forward"]:
            self.camera_velocity = self.speed_scaling
        elif self.key_map["backward"]:
            self.camera_velocity = -self.speed_scaling
        else:
            self.camera_velocity = 0.0
        
        self.camera_velocity = (int(self.treadmill.data.speed) / self.cfg["treadmill_speed_scaling"])

        # Update camera position (movement along the Y axis)
        self.camera_position += self.camera_velocity * dt
        move_distance = self.camera_velocity * dt
        self.camera.setPos(0, self.camera_position, self.camera_height)
        
        # Recycle corridor segments when the camera moves beyond one segment length
        # Forward movement -----> Recycle segments from the back to the front
        if move_distance > 0:
            self.distance_since_recycle += move_distance
            while self.distance_since_recycle >= self.segment_length:
                self.corridor.recycle_segment(direction="forward")
                self.distance_since_recycle -= self.segment_length
                self.corridor.segments_until_texture_change -= 1  # Decrement the texture change counter
                self.corridor.update_texture_change()  # Check and update texture change logic
        # Backward movement <----- Recycle segments from the front to the back
        elif move_distance < 0:
            self.distance_since_recycle += move_distance
            while self.distance_since_recycle <= -self.segment_length:
                self.corridor.recycle_segment(direction="backward")
                self.distance_since_recycle += self.segment_length
                #self.corridor.segments_until_texture_change -= 1  # Decrement the texture change counter
                self.corridor.update_texture_change()  # Check and update texture change logic
        
        # Log movement data (timestamp, distance, speed)
        self.data_logger.log(self.treadmill.data)
        
        return Task.cont

if __name__ == "__main__":
    app = MousePortal("cfg.json")
    app.run()