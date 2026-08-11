"""
Photodiode sync patch.

A luminance square in a screen corner, driven one level per frame.  The
commanded level is written to every sample row, so a photodiode trace recorded
alongside the session decodes against the ``sync_level`` column and turns the
software's estimate of presentation time into a measured quantity.

The default policy toggles every frame, giving the photodiode a transition at
every flip.  ``mark()`` holds the patch high for a run of frames, which shows
up as a gap in the transition series and makes a specific moment findable
without decoding the whole trace.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from panda3d.core import CardMaker

from mouseportal.config import SyncPatchConfig

if TYPE_CHECKING:
    from direct.showbase.ShowBase import ShowBase


# render2d spans -1..1 in both axes regardless of window aspect, so these are
# exact screen corners.
_CORNERS = {
    "top-left": (-1.0, 1.0),
    "top-right": (1.0, 1.0),
    "bottom-left": (-1.0, -1.0),
    "bottom-right": (1.0, -1.0),
}


class SyncPatch:
    """Screen-corner quad whose luminance is logged per frame."""

    def __init__(self, base: "ShowBase", cfg: SyncPatchConfig) -> None:
        self.cfg = cfg
        self._level = cfg.low
        self._mark_frames = 0

        corner_x, corner_y = _CORNERS[cfg.corner]
        span = 2.0 * cfg.size  # cfg.size is a fraction of the screen
        inner_x = corner_x - corner_x * span
        inner_y = corner_y - corner_y * span

        cm = CardMaker("sync-patch")
        cm.setFrame(
            min(corner_x, inner_x), max(corner_x, inner_x),
            min(corner_y, inner_y), max(corner_y, inner_y),
        )
        self.node = base.render2d.attachNewNode(cm.generate())
        self.node.setBin("fixed", 100)
        self.node.setDepthTest(False)
        self.node.setDepthWrite(False)
        self.node.setLightOff()
        self._apply()

    @property
    def level(self) -> float:
        """The luminance commanded for the frame currently being drawn."""
        return self._level

    def advance(self) -> float:
        """Pick this frame's level. Call once per frame, before the draw."""
        if self._mark_frames > 0:
            self._mark_frames -= 1
            self._level = self.cfg.high
        elif self._level == self.cfg.high:
            self._level = self.cfg.low
        else:
            self._level = self.cfg.high
        self._apply()
        return self._level

    def mark(self, frames: int = 4) -> None:
        """Hold the patch high for the next ``frames`` frames."""
        self._mark_frames = frames

    def _apply(self) -> None:
        v = self._level
        self.node.setColor(v, v, v, 1.0)

    def close(self) -> None:
        self.node.removeNode()
