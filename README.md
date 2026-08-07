# <img src="https://github.com/user-attachments/assets/3db5432d-7a35-40df-a91f-4387e241ee24" width="120" height="70"> Mouse Portal 

Infinite virtual corridor stimulus built on [Panda3D](https://www.panda3d.org/) for rodent treadmill / behavioral-neuroscience experiments.

A subject runs on a treadmill; encoder velocity drives a first-person camera down a procedurally recycled corridor. A block/trial state machine sequences experimental conditions, and per-trial **velocity transforms** (gain, freeze, invert, delay, …) enable open-loop "glitch" paradigms. Data logged per-frame to CSV. Currently designed around input from [Janelia Frictionless Treadmill Interface](https://github.com/janelia-experimental-technology/Treadmill-Interface/tree/main/Firmware/EncoderInterfaceT4).

## Features

- **Infinite corridor** — a static scene graph with ring-buffered segment
  recycling; see [below](#infinite-corridor).

- **JSON config, validated on load**: the config is a tree of frozen
  dataclasses, and each one checks its own invariants in `__post_init__`
  (`num_segments >= 3`, positive `speed_scaling`, fog color in [0,1], …).
  `PortalConfig.from_json` builds the tree.

- **Unified Input facade**: `keyboard`, `serial` (Teensy encoder),
  or `network` (UDP). The serial reader is a Panda3D task that publishes over
  the messenger, running the render thread at frame rate. The UDP receiver is
  a daemon thread holding the latest sample independent of the render loop.
  Keyboard is held-key state. The rest of the app reads one property, `InputManager.velocity`.

- **Block/trial state machine**: an explicit `ExperimentState` enum advanced by
  one call per frame, `tick(dt, position)`. Trial-end rules are per condition
  (`distance`, `duration`, `manual`) and resolve at trial onset, condition
  override first and global config second, active parameters hold for the
  whole trial. Each transition emits a structured event through a `send_event`
  callable for testabilty.

- **Velocity transforms**: `raw → transform(velocity, dt, position) → camera`.
  Stateless kernels (`identity`, `gain`, `offset`, `invert`, `clamp`, `freeze`)
  and stateful ones (`noisy`, and `delay`) share call signature and a `reset()`
  at trial onset, A string-keyed registry (`build_transform`) constructs them from JSON.

- **Per-frame CSV logging**: one flat table carrying continuous samples and
  discrete events under a fixed schema. Paths follow BIDS
  (`sub-<id>/ses-<id>/beh/..._portal.csv`), and an orchestrator can hand over an
  explicit `output_path` to use verbatim. An `on_row` hook exposes the same rows
  for live streaming.

  | timestamp | datetime | frame | state | block | trial | condition | position | velocity | effective_velocity | treadmill_device_us | event |
  |---|---|---|---|---|---|---|---|---|---|---|---|
  | 1775174683.4671 | 2026-04-03T00:04:43.467092+00:00 | 900 | | 0 | 0 | | | | | | `experiment.TRIAL_RUNNING\|{'from': 'BLOCK_START', 'to': 'TRIAL_RUNNING', 'block': 1, 'trial': 1, 'condition': 'normal', 'transform': 'identity'}` |
  | 1775174683.4756 | 2026-04-03T00:04:43.475640+00:00 | 901 | TRIAL_RUNNING | 1 | 1 | normal | 47.650166 | 20.0 | 20.0 | 41230118 | |
  | 1775174683.4923 | 2026-04-03T00:04:43.492301+00:00 | 902 | TRIAL_RUNNING | 1 | 1 | normal | 47.983499 | 20.0 | 20.0 | 41246785 | |
  | 1775174691.1082 | 2026-04-03T00:04:51.108214+00:00 | 1358 | TRIAL_RUNNING | 1 | 2 | glitch_gain | 152.114832 | 19.4 | 38.8 | 48862351 | |
  | 1775174691.1249 | 2026-04-03T00:04:51.124881+00:00 | 1359 | TRIAL_RUNNING | 1 | 2 | glitch_gain | 152.761498 | 19.4 | 38.8 | 48879018 | |

  `velocity` is what the treadmill reported and `effective_velocity` is what the
  camera moved on, so the per-frame manipulation is recoverable from the record.
  `treadmill_device_us` is the encoder's own microsecond clock, the anchor for
  aligning the corridor against imaging offline. Event rows share the frame
  counter and clock with the samples around them, which places every transition
  in the same timeline as the movement.

- **Integration surface**: window size and origin are given in OS
  virtual-desktop coordinates for dual-monitor targeting. `--autostart` begins
  the session on launch, and a `MOUSEPORTAL_READY` token on stdout gives a
  parent process (e.g. mesofield) a handshake signal.

### Infinite corridor

**Geometry.** The corridor is cut along its long axis (+Y) into identical
*slices*. Each slice is four axis-aligned quads — left wall, right wall, ceiling,
floor — emitted by Panda3D's `CardMaker` and attached as `NodePath`s under a
single `corridor` parent in the scene graph. Every face holds its own texture
binding; wall, floor, and ceiling textures can be set independently. The entire scene
is `4 × (num_segments + 2)` quads, built once at startup and reused for the rest
of the session. 

**Recycling.** Slices live in a `collections.deque` used as a fixed-capacity ring
buffer. The world stays still and the camera translates, so the camera's Y is the
integrated position signal. An accumulator tracks distance since the last
recycle; each time it crosses ±`segment_length`, the trailing slice is popped and
re-attached at the leading end with one `setY` across its four faces. Each recycle
is O(1) and allocation-free, and the steady-state draw count holds constant.

**Rendering.** Forward-rasterized and single-pass. Corridor extent is masked by
exponential fog (`Fog.setExpDensity`) with the framebuffer clear color set to the
fog color, so the leading slice boundary and the far clip plane dissolve into one
uniform field. The update task runs in a fixed order every frame — input → state
machine → velocity transform → camera integration → recycle → log — which keeps
the logged position and the rendered position on the same `dt`.

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
