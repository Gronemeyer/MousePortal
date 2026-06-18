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

Per-frame CSV output (BIDS path: `data/sub-{id}/ses-{id}/beh/...`) includes:

| Column | Description |
|---|---|
| `timestamp` | Unix epoch (float) |
| `datetime` | ISO-8601 UTC |
| `frame` | Frame counter |
| `state` | Experiment state (`IDLE`, `TRIAL_RUNNING`, `INTER_TRIAL_INTERVAL`, …) |
| `block` | Current block (1-indexed) |
| `trial` | Current trial within block (1-indexed) |
| `condition` | Active condition label (e.g. `"normal"`, `"freeze"`) |
| `position` | Camera Y position |
| `velocity` | Raw input velocity |
| `effective_velocity` | Velocity after transform |
| `treadmill_device_us` | Treadmill device microsecond clock (serial/network input; `0` for keyboard) — anchor for offline sync |
| `event` | Discrete event markers (state transitions) |

The difference between `velocity` and `effective_velocity` is the transform's
effect. For analysis, use `effective_velocity` to reconstruct visual flow and
`velocity` to reconstruct the subject's locomotor behaviour.

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
