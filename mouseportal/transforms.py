"""
Velocity transforms — the mechanism for glitch trials.

A VelocityTransform sits between raw input and camera movement::

    raw_velocity → [VelocityTransform] → effective_velocity → camera.setY()

Each transform is a small callable class.  Stateless transforms (gain,
invert, clamp) are trivial; stateful ones (delay, noisy) carry internal
buffers but still expose the same ``__call__`` interface.

A ``build_transform`` factory maps config strings to concrete instances
so the rest of the code never imports individual classes.
"""

from __future__ import annotations

import random
from abc import ABC, abstractmethod
from collections import deque
from typing import Any, Dict


# ─── Abstract base ──────────────────────────────────────────────────────────

class VelocityTransform(ABC):
    """Protocol for all velocity transforms."""

    @abstractmethod
    def __call__(self, velocity: float, dt: float, position: float) -> float:
        """
        Transform a raw velocity value.

        Parameters
        ----------
        velocity : float
            Raw input velocity (units / sec).
        dt : float
            Frame delta-time in seconds.
        position : float
            Current camera position along the corridor.

        Returns
        -------
        float
            Effective velocity after the transform.
        """

    def reset(self) -> None:
        """Reset any internal state (called at trial start)."""


# ─── Concrete transforms ────────────────────────────────────────────────────

class IdentityTransform(VelocityTransform):
    """Passthrough — no modification.  Used for normal / control trials."""

    def __call__(self, velocity: float, dt: float, position: float) -> float:
        return velocity


class GainTransform(VelocityTransform):
    """Scale velocity by a constant gain factor."""

    def __init__(self, gain: float = 1.0) -> None:
        if gain < 0:
            raise ValueError(f"gain must be non-negative: {gain}")
        self.gain = gain

    def __call__(self, velocity: float, dt: float, position: float) -> float:
        return velocity * self.gain


class FreezeTransform(VelocityTransform):
    """Open-loop freeze — velocity is forced to zero."""

    def __call__(self, velocity: float, dt: float, position: float) -> float:
        return 0.0


class OffsetTransform(VelocityTransform):
    """Add a constant drift to the velocity."""

    def __init__(self, offset: float = 0.0) -> None:
        self.offset = offset

    def __call__(self, velocity: float, dt: float, position: float) -> float:
        return velocity + self.offset


class InvertTransform(VelocityTransform):
    """Reverse the direction of movement."""

    def __call__(self, velocity: float, dt: float, position: float) -> float:
        return -velocity


class ReverseTransform(VelocityTransform):
    """Open-loop reversal — the corridor runs backward at a fixed speed.

    Unlike ``invert``, the input is ignored entirely: the camera moves
    backward whether or not the subject is running.
    """

    def __init__(self, speed: float = 20.0) -> None:
        if speed < 0:
            raise ValueError(f"speed must be non-negative: {speed}")
        self.speed = speed

    def __call__(self, velocity: float, dt: float, position: float) -> float:
        return -self.speed


class ClampTransform(VelocityTransform):
    """Clamp velocity to a [lo, hi] range."""

    def __init__(self, lo: float = 0.0, hi: float = 10.0) -> None:
        if lo > hi:
            raise ValueError(f"lo must be <= hi: lo={lo}, hi={hi}")
        self.lo = lo
        self.hi = hi

    def __call__(self, velocity: float, dt: float, position: float) -> float:
        return max(self.lo, min(self.hi, velocity))


class NoisyTransform(VelocityTransform):
    """Add Gaussian noise to velocity each frame."""

    def __init__(self, sigma: float = 1.0) -> None:
        if sigma < 0:
            raise ValueError(f"sigma must be non-negative: {sigma}")
        self.sigma = sigma

    def __call__(self, velocity: float, dt: float, position: float) -> float:
        return velocity + random.gauss(0.0, self.sigma)


class DelayTransform(VelocityTransform):
    """
    Temporal delay — returns the velocity from ``delay_sec`` seconds ago.

    Uses a ring-buffer of past samples.  Until the buffer fills, the
    output is zero (the corridor is frozen at trial onset, then begins
    playing back the delayed movement).
    """

    def __init__(self, delay_sec: float = 0.2) -> None:
        if delay_sec < 0:
            raise ValueError(f"delay_sec must be non-negative: {delay_sec}")
        self.delay_sec = delay_sec
        self._buffer: deque[tuple[float, float]] = deque()  # (elapsed, velocity)
        self._elapsed: float = 0.0

    def __call__(self, velocity: float, dt: float, position: float) -> float:
        self._elapsed += dt
        self._buffer.append((self._elapsed, velocity))

        # Find the sample closest to (now - delay).
        target = self._elapsed - self.delay_sec
        if target <= 0.0:
            return 0.0

        # Pop samples older than target, keep the most recent one before it.
        delayed_v = 0.0
        while len(self._buffer) > 1 and self._buffer[0][0] < target:
            delayed_v = self._buffer.popleft()[1]
        if self._buffer and self._buffer[0][0] <= target:
            delayed_v = self._buffer[0][1]

        return delayed_v

    def reset(self) -> None:
        self._buffer.clear()
        self._elapsed = 0.0


# ─── Factory ────────────────────────────────────────────────────────────────

_REGISTRY: Dict[str, type] = {
    "identity": IdentityTransform,
    "gain": GainTransform,
    "freeze": FreezeTransform,
    "offset": OffsetTransform,
    "invert": InvertTransform,
    "reverse": ReverseTransform,
    "clamp": ClampTransform,
    "noisy": NoisyTransform,
    "delay": DelayTransform,
}


def build_transform(transform_type: str, params: Dict[str, Any] | None = None) -> VelocityTransform:
    """
    Build a VelocityTransform from a type string and optional parameters.

    Parameters
    ----------
    transform_type : str
        Key in the transform registry (e.g. ``"gain"``, ``"freeze"``).
    params : dict, optional
        Keyword arguments forwarded to the transform constructor.

    Returns
    -------
    VelocityTransform

    Raises
    ------
    ValueError
        If ``transform_type`` is not recognised.
    """
    cls = _REGISTRY.get(transform_type)
    if cls is None:
        known = ", ".join(sorted(_REGISTRY))
        raise ValueError(
            f"Unknown transform type '{transform_type}'. "
            f"Available: {known}"
        )
    return cls(**(params or {}))
