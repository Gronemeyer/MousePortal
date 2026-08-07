"""
Fog effect wrapper for the corridor scene.

Exponential fog hides the corridor endpoints, creating the seamless
infinite-hallway illusion.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Tuple

from panda3d.core import Fog

if TYPE_CHECKING:
    from direct.showbase.ShowBase import ShowBase
    from mouseportal.config import FogConfig


class FogEffect:
    """Apply exponential fog to the Panda3D scene."""

    def __init__(self, base: "ShowBase", cfg: "FogConfig") -> None:
        self.base = base
        self.fog = Fog("corridor_fog")

        # Background color matches fog color for a seamless blend.
        base.setBackgroundColor(cfg.color)
        self.fog.setColor(*cfg.color)
        self.fog.setExpDensity(cfg.density)

        # Attach to the base render node (not the global ``render``).
        base.render.setFog(self.fog)
