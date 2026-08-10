"""Focus-independent keyboard trigger.

This watcher polls global key state. It is Windows-only (``GetAsyncKeyState``); 
elsewhere :attr:`available` is False and MousePortal falls back to its focused-window
``accept("space")`` binding.
"""

from __future__ import annotations

VK_SPACE = 0x20


class GlobalKeyWatcher:
    """Edge-detects a virtual-key press regardless of window focus.

    Poll :meth:`pressed` once per frame; it returns True on the frame where the
    key transitions from up to down.
    """

    def __init__(self, vk: int = VK_SPACE) -> None:
        self._vk = vk
        self._down = False
        self._user32 = None
        try:
            import ctypes

            user32 = ctypes.WinDLL("user32", use_last_error=True)
            user32.GetAsyncKeyState.restype = ctypes.c_short
            user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
            self._user32 = user32
            # Clear any latched state so a key already held at construction is
            # not reported as a fresh press on the first poll.
            self._down = self._is_down()
        except Exception:
            self._user32 = None

    @property
    def available(self) -> bool:
        """True when global key state can actually be read on this platform."""
        return self._user32 is not None

    def pressed(self) -> bool:
        """True once per up->down transition of the watched key."""
        if self._user32 is None:
            return False
        down = self._is_down()
        rising = down and not self._down
        self._down = down
        return rising

    def _is_down(self) -> bool:
        # Bit 0x8000 is the current physical state; the low bit ("pressed since
        # last call") is shared process-wide and unreliable, so edge-detect the
        # high bit ourselves.
        return bool(self._user32.GetAsyncKeyState(self._vk) & 0x8000)
