"""
MousePortal — Infinite corridor stimulus for Panda3D.

A configurable, scientifically-oriented virtual corridor for
rodent treadmill experiments. Designed for clear parameterization,
fail-fast validation, and extensible experiment control.

Author: Jake Gronemeyer
"""

try:
    from mouseportal._version import version as __version__
except ImportError:
    # Package not installed (running from source without pip install -e).
    __version__ = "0.0.0-dev"
