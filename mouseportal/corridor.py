"""
Corridor geometry — segment ring-buffer for the infinite hallway illusion.

Segments are built once at startup using Panda3D's CardMaker, then
recycled from one end to the other as the camera advances. A
collections.deque provides O(1) append/popleft for this pattern.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import TYPE_CHECKING

from panda3d.core import CardMaker, NodePath, Texture

if TYPE_CHECKING:
    from direct.showbase.ShowBase import ShowBase
    from mouseportal.config import CorridorConfig


@dataclass
class SegmentSlice:
    """The four faces (left wall, right wall, ceiling, floor) for one corridor slice."""
    left: NodePath
    right: NodePath
    ceiling: NodePath
    floor: NodePath

    @property
    def y(self) -> float:
        """Y position of this slice (all four faces share the same Y)."""
        return self.left.getY()

    def set_y(self, y: float) -> None:
        """Reposition all four faces to a new Y coordinate."""
        self.left.setY(y)
        self.right.setY(y)
        self.ceiling.setY(y)
        self.floor.setY(y)


class Corridor:
    """
    Generates and manages an infinite corridor via segment recycling.

    The corridor is a ring-buffer of ``SegmentSlice`` objects stored in a
    ``deque``.  When the camera advances past one ``segment_length``, the
    trailing slice is popped and re-appended at the leading end (and
    vice-versa for backward movement).
    """

    def __init__(self, base: "ShowBase", cfg: "CorridorConfig") -> None:
        self.base = base
        self.segment_length: float = cfg.segment_length
        self.corridor_width: float = cfg.corridor_width
        self.wall_height: float = cfg.wall_height
        self.num_segments: int = cfg.num_segments

        self.left_wall_texture: str = cfg.left_wall_texture
        self.right_wall_texture: str = cfg.right_wall_texture
        self.ceiling_texture: str = cfg.ceiling_texture
        self.floor_texture: str = cfg.floor_texture

        # Parent scene-graph node for all corridor geometry.
        self.parent: NodePath = base.render.attachNewNode("corridor")

        # Ring-buffer of segment slices.
        self.segments: deque[SegmentSlice] = deque()

        self._build_segments()

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def _build_segments(self) -> None:
        """Build the initial corridor segments using CardMaker."""
        for i in range(self.num_segments):
            y_start: float = i * self.segment_length
            seg = self._make_slice(y_start)
            self.segments.append(seg)

    def _make_slice(self, y: float) -> SegmentSlice:
        """Create a single four-face corridor slice at the given Y position."""
        sl = self.segment_length
        hw = self.corridor_width / 2.0
        wh = self.wall_height

        # ---- Left wall ----
        cm = CardMaker("left_wall")
        cm.setFrame(0, sl, 0, wh)
        left = self.parent.attachNewNode(cm.generate())
        left.setPos(-hw, y, 0)
        left.setHpr(90, 0, 0)
        self._apply_texture(left, self.left_wall_texture)

        # ---- Right wall ----
        cm = CardMaker("right_wall")
        cm.setFrame(0, sl, 0, wh)
        right = self.parent.attachNewNode(cm.generate())
        right.setPos(hw, y, 0)
        right.setHpr(-90, 0, 0)
        self._apply_texture(right, self.right_wall_texture)

        # ---- Ceiling ----
        cm = CardMaker("ceiling")
        cm.setFrame(-hw, hw, 0, sl)
        ceiling = self.parent.attachNewNode(cm.generate())
        ceiling.setPos(0, y, wh)
        ceiling.setHpr(0, 90, 0)
        self._apply_texture(ceiling, self.ceiling_texture)

        # ---- Floor ----
        cm = CardMaker("floor")
        cm.setFrame(-hw, hw, 0, sl)
        floor = self.parent.attachNewNode(cm.generate())
        floor.setPos(0, y, 0)
        floor.setHpr(0, -90, 0)
        self._apply_texture(floor, self.floor_texture)

        return SegmentSlice(left=left, right=right, ceiling=ceiling, floor=floor)

    def _apply_texture(self, node: NodePath, texture_path: str) -> None:
        """Load and apply a texture to a node."""
        tex: Texture = self.base.loader.loadTexture(texture_path)
        node.setTexture(tex)

    # ------------------------------------------------------------------
    # Recycling
    # ------------------------------------------------------------------

    def recycle_forward(self) -> None:
        """Pop the trailing (oldest) slice and append it past the leading end."""
        new_y = self.segments[-1].y + self.segment_length
        seg = self.segments.popleft()
        seg.set_y(new_y)
        self.segments.append(seg)

    def recycle_backward(self) -> None:
        """Pop the leading slice and prepend it before the trailing end."""
        new_y = self.segments[0].y - self.segment_length
        seg = self.segments.pop()
        seg.set_y(new_y)
        self.segments.appendleft(seg)
