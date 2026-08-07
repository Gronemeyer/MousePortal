# Mouse Portal <img src="https://github.com/user-attachments/assets/3db5432d-7a35-40df-a91f-4387e241ee24" width="120" height="70">

Infinite virtual corridor stimulus built on [Panda3D](https://www.panda3d.org/) for rodent treadmill / behavioral-neuroscience experiments.

A subject runs on a treadmill; encoder velocity drives a first-person camera down a procedurally recycled corridor. A block/trial state machine sequences experimental conditions, and per-trial **velocity transforms** (gain, freeze, invert, delay, …) enable open-loop "glitch" paradigms. Every frame is logged to a BIDS-style CSV.

## Features

- **JSON-parameterized** — all settings validated at startup (fail-fast).
- **Infinite corridor** — segments recycled front/back, never re-rendered from scratch.
- **Multiple input modes** — `keyboard`, `serial` (Teensy encoder), or `network` (UDP from an orchestrator).
- **Block/trial state machine** — blocks, trials, inter-trial intervals; distance-, duration-, or manual-ended trials.
- **Velocity transforms** — `identity`, `gain`, `freeze`, `offset`, `invert`, `clamp`, `noisy`, `delay`, applied per condition.
- **CSV data logging** — per-frame rows + discrete events, BIDS-compliant paths.
- **Headless simulation** (`simulate.py`) and **analysis plots** (`visualize.py`).
- **Multi-monitor** window placement and **orchestrator integration** (autostart + `MOUSEPORTAL_READY` handshake, e.g. mesofield).

## Install

Requires Python ≥ 3.11.

```bash
git clone https://github.com/Gronemeyer/MousePortal.git
cd MousePortal
pip install -e .          # installs panda3d + pyserial, adds `mouseportal` command
```

For simulation/analysis tooling: `pip install pandas matplotlib numpy`.

## Usage

```bash
mouseportal                    # run with cfg.json (or: python runportal.py)
mouseportal -c my.json         # custom config
mouseportal --init             # write a default cfg.json
mouseportal --autostart        # start immediately (for external orchestrators)
```

In-app keys: **Space** start / end trial · **F1** toggle debug HUD · **Esc** quit.

### Simulate & visualize (no graphics)

```bash
python simulate.py -c cfg.json --seed 42      # synthetic mouse → CSV
python visualize.py data/.../sub-001_..._portal.csv   # 6-panel analysis figure
```

## Configuration

Config is a nested JSON file (see [cfg.json](cfg.json)) with these sections:

| Section | Purpose |
|---|---|
| `window` | Size and multi-monitor origin |
| `corridor` | Segment geometry, counts, wall/floor/ceiling textures |
| `camera` | Height, `speed_scaling` (encoder), `keyboard_speed` |
| `fog` | Density and color |
| `input` | `mode` (`keyboard`/`serial`/`network`), serial port/baud, UDP host/port |
| `experiment` | Blocks, trials, ITI, end condition, `conditions` + `block_conditions` |
| `triggers` | Optional serial trigger output |
| `logging` | `subject`/`session`/`task` (BIDS) or explicit `output_path` |

Each `condition` selects a velocity transform and optional per-condition trial-end overrides; `block_conditions` define the per-trial sequence of condition labels for each block.

## Layout

```
mouseportal/
  app.py          # Panda3D orchestrator + CLI entry point
  config.py       # validated config dataclasses
  input.py        # keyboard / serial / network backends
  corridor.py     # infinite corridor geometry & recycling
  experiment.py   # block/trial state machine
  transforms.py   # velocity transforms (glitch mechanism)
  datalog.py      # CSV logger (per-frame + events)
  fog.py, zones.py, triggers.py
runportal.py      # thin launcher
simulate.py       # headless experiment runner
visualize.py      # CSV → analysis figure
docs/glitch-experiment.md
```

See [docs/glitch-experiment.md](docs/glitch-experiment.md) for the glitch-experiment design.

Author: Jacob Gronemeyer · License: BSD-2-Clause
