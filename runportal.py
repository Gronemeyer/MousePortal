#!/usr/bin/env python3
"""
MousePortal — Infinite corridor stimulus for Panda3D.

Entry point.  All logic lives in the ``mouseportal`` package.
Run with:
    python runportal.py              # uses cfg.json
    python runportal.py -c my.json   # uses custom config

Author: Jake Gronemeyer
Version: 0.3
"""

from mouseportal.app import main

if __name__ == "__main__":
    main()
