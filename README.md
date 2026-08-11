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

- **Three-table logging**: continuous samples, discrete events, and trial
  summaries in separate files, each with a schema where every column applies to
  every row. Paths follow BIDS (`sub-<id>/ses-<id>/beh/..._portal-*.csv`), and
  an orchestrator can hand over an explicit `output_path` to use as the stem. An
  `on_row` hook exposes the same rows for live streaming. Absent values are
  `n/a`, which pandas reads as `NaN`.

  `…-samples.csv` — one row per rendered frame:

  | frame | timestamp | flip_timestamp | flip_wait | dropped | state | block | trial | condition | position | velocity | effective_velocity | treadmill_device_us | treadmill_age |
  |---|---|---|---|---|---|---|---|---|---|---|---|---|---|
  | 901 | 1775174683.4756 | 1775174683.4817 | 0.000188 | 0 | TRIAL_RUNNING | 1 | 1 | normal | 47.650166 | 20.0 | 20.0 | 41230118 | 0.0031 |
  | 902 | 1775174683.4817 | 1775174683.4878 | 0.000174 | 0 | TRIAL_RUNNING | 1 | 1 | normal | 47.983499 | 20.0 | 20.0 | 41246785 | 0.0028 |

  `…-events.csv` — one row per discrete event, in long format:

  | timestamp | flip_timestamp | frame | block | trial | event | condition | value |
  |---|---|---|---|---|---|---|---|
  | 1775174691.1082 | 1775174691.1143 | 1358 | 1 | 2 | TRIAL_START | gain_2x | n/a |
  | 1775174694.1149 | 1775174694.1210 | 1855 | 1 | 2 | TRIAL_END | gain_2x | distance |

  `…-trials.csv` adds one row per completed trial (duration, distance, end rule,
  frame and drop counts, velocity means), and `…-timing.json` carries the clock
  anchor, display settings, and measured refresh interval.

  `velocity` is what the treadmill reported and `effective_velocity` is what the
  camera moved on, so the per-frame manipulation is recoverable from the record.
  `treadmill_device_us` is the encoder's own microsecond clock, the anchor for
  aligning the corridor against imaging offline, and `treadmill_age` says how
  stale that reading was when the frame used it. Events carry the `frame` of the
  sample row they belong to, which places every transition in the same timeline
  as the movement.

- **Explicit presentation timing**: all timestamps come from Panda3D's
  QPC-backed `globalClock` and are mapped onto the Unix epoch through a single
  anchor recorded in the sidecar, so rows are epoch-comparable without
  inheriting `time.time()`'s 15.6 ms Windows resolution or its NTP steps. A task
  at sort 55 brackets `readyFlip()`/`flipFrame()` with clock reads, so
  `flip_timestamp` is a measured buffer swap rather than an inferred one, and
  frame drops are flagged against the running median flip interval. An optional
  photodiode patch logs its commanded luminance per frame, which is what turns
  the software-to-photon offset into something measurable. See
  [docs/glitch-experiment.md](docs/glitch-experiment.md) for the full model.

- **Integration surface**: window size and origin are given in OS
  virtual-desktop coordinates for dual-monitor targeting. `--autostart` begins
  the session on launch, and a `MOUSEPORTAL_READY` token on stdout gives a
  parent process (e.g. mesofield) a handshake signal. `--wait-trigger` instead
  holds the session frozen after that handshake until the run's spacebar
  trigger, detected globally so the press need not land on the MousePortal
  window; the press is written to the events table as `SESSION_TRIGGER` and
  echoed on stdout as `MOUSEPORTAL_TRIGGER <unix_time> <source>` — the same
  timestamp in both places.

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
mouseportal --wait-trigger     # hold until the spacebar trigger, and log its time
```

In-app keys: **Space** start / end trial · **F1** toggle debug HUD · **Esc** quit.

### Simulate & visualize (no graphics)

```bash
python simulate.py -c cfg.json --seed 42      # synthetic mouse → the three tables
python visualize.py data/.../sub-001_..._portal   # 6-panel analysis figure
```

`visualize.py` takes the session stem, or any one of its files.

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
| `logging` | `subject`/`session`/`task` (BIDS) or explicit `output_path` stem |
| `timing` | `explicit_flip`, `sync_video`, `dropped_frame_threshold` |
| `sync_patch` | Photodiode patch corner, size, and luminance levels |

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
  datalog.py      # samples / events / trials tables + timing sidecar
  clock.py        # monotonic timebase with a Unix epoch anchor
  syncpatch.py    # photodiode luminance patch
  fog.py, zones.py, triggers.py
runportal.py      # thin launcher
simulate.py       # headless experiment runner
visualize.py      # session → analysis figure
docs/glitch-experiment.md
```

See [docs/glitch-experiment.md](docs/glitch-experiment.md) for the glitch-experiment design.

Author: Jacob Gronemeyer · License: BSD-2-Clause
