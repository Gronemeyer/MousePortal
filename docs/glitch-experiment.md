# Glitch Experiment — Configuration Guide

The glitch paradigm presents blocks and trials of normal visual flow interleaved
with controlled disruptions ("glitches") of the closed-loop relationship between
input and corridor movement. All configuration lives in `cfg.json`.

---

## How It Works

Every frame, the update loop reads raw velocity from the input device and passes
it through a **velocity transform** before moving the camera:

```
treadmill / keyboard  →  raw velocity  →  [VelocityTransform]  →  effective velocity  →  camera
```

During **normal** trials the transform is an identity (passthrough). During
**glitch** trials a different transform alters the mapping — freezing movement,
scaling it, inverting it, adding noise, or introducing temporal lag.

The transform, trial-end rule, and all associated parameters are set
**per-condition** in the config. The experiment state machine resolves the
active condition at the start of each trial.

---

## Quick Start

Copy this into the `"experiment"` section of `cfg.json`:

```json
"experiment": {
    "num_blocks": 2,
    "trials_per_block": 4,
    "iti_duration": 3.0,
    "trial_end_condition": "distance",
    "trial_distance": 50.0,
    "trial_duration": 60.0,

    "conditions": [
        {"label": "normal",  "transform_type": "identity"},
        {"label": "freeze",  "transform_type": "freeze",
         "trial_end_condition": "duration", "trial_duration": 10.0},
        {"label": "gain_2x", "transform_type": "gain",
         "transform_params": {"gain": 2.0}},
        {"label": "invert",  "transform_type": "invert"}
    ],

    "block_conditions": [
        {"condition_sequence": ["normal", "freeze", "normal", "gain_2x"]},
        {"condition_sequence": ["invert", "normal", "freeze", "normal"]}
    ]
}
```

Then run:

```bash
mouseportal                  # uses cfg.json (or: python runportal.py)
mouseportal -c my_exp.json   # uses a custom config
```

Press **Space** to start the session. The state machine advances automatically
through blocks and trials. Press **F1** to toggle the debug HUD, **Esc** to quit.

---

## Config Reference

### Global experiment parameters

These set the defaults for all trials. Any of the trial-end fields can be
overridden per-condition (see below).

| Field | Type | Default | Description |
|---|---|---|---|
| `num_blocks` | int | `1` | Total number of blocks in the session |
| `trials_per_block` | int | `1` | Trials per block |
| `iti_duration` | float | `2.0` | Inter-trial interval in seconds |
| `trial_end_condition` | string | `"manual"` | Default end rule: `"distance"`, `"duration"`, or `"manual"` |
| `trial_distance` | float | `100.0` | Target distance for `"distance"` end rule (corridor units) |
| `trial_duration` | float | `60.0` | Target time for `"duration"` end rule (seconds) |

### `conditions` — the palette of trial types

A list of condition objects. Each defines a label, a velocity transform, and
optional trial-end overrides.

| Field | Type | Required | Description |
|---|---|---|---|
| `label` | string | **yes** | Unique name referenced by `block_conditions` and logged in the CSV |
| `transform_type` | string | **yes** | Transform key (see table below) |
| `transform_params` | object | no | Parameters forwarded to the transform constructor |
| `trial_end_condition` | string | no | Override: `"distance"`, `"duration"`, or `"manual"` |
| `trial_distance` | float | no | Override target distance |
| `trial_duration` | float | no | Override target duration |

When an override field is omitted (or `null`), the global value is used.

### `block_conditions` — trial ordering per block

A list with one entry per block. Each entry has a `condition_sequence` array
of condition labels — one per trial, in order.

```json
"block_conditions": [
    {"condition_sequence": ["normal", "freeze", "normal", "gain_2x"]},
    {"condition_sequence": ["invert", "normal", "freeze", "normal"]}
]
```

The length of each `condition_sequence` must equal `trials_per_block`.  
If `block_conditions` or `conditions` is empty/absent, every trial defaults to
`"identity"` (normal) — fully backward compatible with older configs.

---

## Available Transforms

| `transform_type` | Effect | Parameters | Example |
|---|---|---|---|
| `identity` | Passthrough | — | `{"label": "normal", "transform_type": "identity"}` |
| `gain` | Scale velocity | `gain` (float) | `{"label": "slow", "transform_type": "gain", "transform_params": {"gain": 0.5}}` |
| `freeze` | Force velocity to 0 | — | `{"label": "freeze", "transform_type": "freeze"}` |
| `offset` | Add constant drift | `offset` (float) | `{"label": "drift", "transform_type": "offset", "transform_params": {"offset": 5.0}}` |
| `invert` | Reverse direction | — | `{"label": "invert", "transform_type": "invert"}` |
| `clamp` | Limit to range | `lo`, `hi` (floats) | `{"label": "limited", "transform_type": "clamp", "transform_params": {"lo": 0, "hi": 10}}` |
| `noisy` | Add Gaussian noise | `sigma` (float) | `{"label": "jitter", "transform_type": "noisy", "transform_params": {"sigma": 3.0}}` |
| `delay` | Temporal lag | `delay_sec` (float) | `{"label": "lag200ms", "transform_type": "delay", "transform_params": {"delay_sec": 0.2}}` |

### Transform behaviour notes

- **`gain`** — a gain of `0.0` is equivalent to `freeze`. A gain of `2.0`
  doubles perceived speed. Negative gains are not allowed (use `invert` + `gain`
  via separate trials if needed).
- **`freeze`** — the subject's input is ignored. The corridor does not move.
  **Important:** pair this with `"trial_end_condition": "duration"` to avoid a
  trial that never ends.
- **`delay`** — until the internal buffer fills (for `delay_sec` seconds), the
  corridor is frozen. After that, movement replays the subject's input from
  `delay_sec` ago. State is reset at each trial boundary.
- **`noisy`** — noise is sampled independently each frame. With a high sigma
  the corridor will jitter even when the subject is stationary.
- **`offset`** — the corridor drifts even when the subject is stationary
  (`velocity = 0 + offset`). Useful for simulating involuntary motion.

---

## Per-Condition Trial-End Overrides

The global `trial_end_condition` is the default for all conditions, but any
condition can override it. This is essential for transforms that prevent the
subject from accumulating distance (e.g. `freeze`, low `gain`).

### Example: freeze with duration fallback

```json
{
    "label": "freeze",
    "transform_type": "freeze",
    "trial_end_condition": "duration",
    "trial_duration": 10.0
}
```

The global end rule is `"distance"` at 50 units, but a freeze trial would never
reach that distance. This condition overrides to `"duration"` at 10 seconds.

### Example: gain-down with longer distance

```json
{
    "label": "gain_half",
    "transform_type": "gain",
    "transform_params": {"gain": 0.5},
    "trial_distance": 100.0
}
```

Still uses the global `"distance"` end rule, but doubles the target so the
subject runs for roughly the same real distance as a normal trial.

### Example: manual condition in an otherwise automated session

```json
{
    "label": "probe",
    "transform_type": "identity",
    "trial_end_condition": "manual"
}
```

This trial runs until the experimenter presses **Space**, even though other
trials end automatically.

---

## Data Output

A session writes four files under a shared stem
(BIDS path: `data/sub-{id}/ses-{id}/beh/sub-{id}_ses-{id}_task-{task}_portal`):

| File | Grain |
|---|---|
| `…-samples.csv` | one row per rendered frame |
| `…-events.csv` | one row per discrete event |
| `…-trials.csv` | one row per completed trial |
| `…-timing.json` | clock anchor, display settings, measured refresh |

Absent values are written as `n/a`, which `pandas.read_csv` parses as `NaN`
without arguments. Files are created exclusively — a rerun with the same
subject/session raises rather than appending to the previous run.

### `samples.csv`

| Column | Unit | Description |
|---|---|---|
| `frame` | | Panda3D global frame count — the join key across all three tables |
| `timestamp` | s | Unix epoch of the start of this frame |
| `flip_timestamp` | s | Unix epoch immediately after the buffer swap returned |
| `flip_wait` | s | Time blocked inside `flipFrame()` |
| `frame_dt` | s | Interval between the previous two frame ticks |
| `dropped` | | 1 when the flip interval exceeded the threshold |
| `sync_level` | | Luminance commanded for the photodiode patch this frame |
| `state` | | `IDLE`, `TRIAL_RUNNING`, `INTER_TRIAL_INTERVAL`, … |
| `block` / `trial` | | 1-indexed; 0 before the session starts |
| `condition` | | Active condition label |
| `position` | corridor units | Camera Y position |
| `velocity` | units/s | Raw input velocity |
| `effective_velocity` | units/s | Velocity after the transform |
| `treadmill_device_us` | µs | Device clock of the most recent encoder sample |
| `treadmill_age` | s | How stale that sample was at this frame's start |

The difference between `velocity` and `effective_velocity` is the transform's
effect. For analysis, use `effective_velocity` to reconstruct visual flow and
`velocity` to reconstruct the subject's locomotor behaviour.

`treadmill_device_us` and `treadmill_age` are `n/a` in keyboard mode.

### `events.csv`

`timestamp`, `flip_timestamp`, `frame`, `block`, `trial`, `event`,
`condition`, `value`.

```
timestamp        flip_timestamp   frame block trial event         condition value
1786402577.6041  1786402577.6097  1     1     0     BLOCK_START   n/a       n/a
1786402577.6041  1786402577.6097  1     1     1     TRIAL_START   invert    n/a
1786402579.1059  1786402579.1114  154   1     1     TRIAL_END     invert    duration
1786402579.1059  1786402579.1114  154   1     1     ITI_START     invert    n/a
```

Tokens: `SESSION_ARMED`, `SESSION_TRIGGER`, `BLOCK_START`, `TRIAL_START`,
`TRIAL_END`, `ITI_START`, `BLOCK_END`, `SESSION_COMPLETE`. The set is open —
`STIMULUS_ONSET`, `RESPONSE` and `REWARD` are reserved for paradigms that
emit them, and need no schema change.

`flip_timestamp` is `n/a` for events with no visual consequence (a trigger
keypress, for instance): there is no presentation time to report.

### `trials.csv`

`block`, `trial`, `condition`, `transform`, `transform_params`,
`start_timestamp`, `end_timestamp`, `duration`, `distance`, `end_rule`,
`n_frames`, `n_dropped`, `mean_velocity`, `mean_effective_velocity`.

Only `TRIAL_RUNNING` frames contribute to the aggregates; ITI frames belong
to no trial.

---

## Timing and Synchronization

### The timebase

Every timestamp is derived from Panda3D's `globalClock`, which is backed by
`QueryPerformanceCounter`: monotonic, ~100 ns resolution, and unaffected by
NTP corrections mid-session. Its epoch is process start, so the session
captures one Unix anchor at startup and reports

```
timestamp = unix_anchor + (clock - clock_anchor)
```

`time.time()` is used only to establish that anchor. On Windows it reports
`GetSystemTimeAsFileTime`, nominal resolution 15.625 ms — coarser than a
frame. The anchor is taken on a system-clock edge, and the observed tick is
recorded as `anchor_residual` in `timing.json`. That residual bounds how far
the *epoch mapping* can be off; precision *within* the session is not
affected by it.

### Presentation time

`updateTask` runs at sort 0, before `igLoop` (sort 50) culls and draws. It
stages the frame's values; `flipTask` at sort 55 completes the row:

```
readyFlip()   # blocks until the GPU has finished drawing
t0 = clock
flipFrame()   # the buffer swap; with vsync, returns at the vertical blank
t1 = clock
```

`flip_timestamp` is `t1` and `flip_wait` is `t1 - t0`. This mirrors the
pattern Panda uses internally for cluster sync. `readyFlip()` forces a
one-pixel GPU readback, which costs throughput and buys a swap that is
measured rather than inferred. Set `timing.explicit_flip` to `false` to skip
it, in which case the swap happens at the start of the next frame's
`render_frame()` and `flip_timestamp` no longer means what it says.

Note that `flip_wait` is only the *tail* of the wait for vblank — some of it
is absorbed by `readyFlip()`. A run at the monitor's refresh rate is the
signal that vsync is working, not a large `flip_wait`.

**`flip_timestamp` is a measured buffer swap, not a photon time.** The
residual between them is fixed hardware latency, and measuring it needs a
photodiode.

### The photodiode patch

With `sync_patch.enabled`, a luminance square is drawn in a screen corner and
toggled every frame, and the level commanded for each frame is written to
`sync_level`. A photodiode trace recorded alongside the session therefore
decodes against that column: join the transitions to `frame`, regress the
photodiode times on `flip_timestamp`, and the software-to-photon offset stops
being an assumption.

### Frame drops

`dropped` is set when the flip interval exceeds
`timing.dropped_frame_threshold` times the running median of observed
intervals. The median adapts to whatever the window is actually running at,
rather than trusting the display's nominal rate. Nothing is flagged until the
first 120 intervals have established it.

### Config

```json
"timing": {
    "explicit_flip": true,
    "sync_video": true,
    "dropped_frame_threshold": 1.5
},
"sync_patch": {
    "enabled": false,
    "corner": "bottom-right",
    "size": 0.08,
    "high": 1.0,
    "low": 0.0
}
```

`sync_video` becomes the `sync-video` PRC variable, which is read when the
window opens — so config is loaded before `ShowBase` is constructed.

---

## Design Recipes

### Minimal: one block, three conditions

```json
"experiment": {
    "num_blocks": 1,
    "trials_per_block": 3,
    "iti_duration": 2.0,
    "trial_end_condition": "duration",
    "trial_duration": 30.0,
    "conditions": [
        {"label": "normal", "transform_type": "identity"},
        {"label": "freeze", "transform_type": "freeze"},
        {"label": "noisy",  "transform_type": "noisy", "transform_params": {"sigma": 5.0}}
    ],
    "block_conditions": [
        {"condition_sequence": ["normal", "freeze", "noisy"]}
    ]
}
```

### Gain titration across blocks

```json
"conditions": [
    {"label": "gain_0.5", "transform_type": "gain", "transform_params": {"gain": 0.5}},
    {"label": "gain_1.0", "transform_type": "identity"},
    {"label": "gain_1.5", "transform_type": "gain", "transform_params": {"gain": 1.5}},
    {"label": "gain_2.0", "transform_type": "gain", "transform_params": {"gain": 2.0}}
],
"block_conditions": [
    {"condition_sequence": ["gain_1.0", "gain_0.5", "gain_1.5", "gain_2.0"]},
    {"condition_sequence": ["gain_2.0", "gain_1.5", "gain_0.5", "gain_1.0"]},
    {"condition_sequence": ["gain_0.5", "gain_2.0", "gain_1.0", "gain_1.5"]}
]
```

### Delay detection threshold

```json
"conditions": [
    {"label": "normal",  "transform_type": "identity"},
    {"label": "lag_50",  "transform_type": "delay", "transform_params": {"delay_sec": 0.05}},
    {"label": "lag_100", "transform_type": "delay", "transform_params": {"delay_sec": 0.1}},
    {"label": "lag_200", "transform_type": "delay", "transform_params": {"delay_sec": 0.2}},
    {"label": "lag_500", "transform_type": "delay", "transform_params": {"delay_sec": 0.5}}
]
```

---

## Extending: Adding a New Transform

1. Add a class to `mouseportal/transforms.py` inheriting from `VelocityTransform`.
2. Implement `__call__(self, velocity, dt, position) -> float`.
3. If stateful, implement `reset()` to clear internal buffers.
4. Register the class in `_REGISTRY` at the bottom of the file.
5. Use it in `cfg.json` by its registry key.

No other files need to change.
