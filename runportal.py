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

import argparse
import sys

from mouseportal.app import MousePortal


def main() -> None:
    parser = argparse.ArgumentParser(description="MousePortal infinite corridor stimulus")
    parser.add_argument(
        "-c", "--config",
        default="cfg.json",
        help="Path to JSON configuration file (default: cfg.json)",
    )
    args = parser.parse_args()

    try:
        app = MousePortal(args.config)
    except (RuntimeError, ValueError) as exc:
        print(f"[MousePortal] startup error: {exc}", file=sys.stderr)
        sys.exit(1)

    app.run()


if __name__ == "__main__":
    main()