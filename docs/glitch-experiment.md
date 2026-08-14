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

The raw velocity reaching that transform is already in corridor units: the
input layer multiplies the encoder's reading by `camera.speed_scaling` first.
That is the session-wide calibration between the animal's running and the
corridor; the transforms are the per-trial manipulation on top of it.

The transform, trial-end rule, and all associated parameters are set
**per-condition** in the config. The experiment state machine resolves the
active condition at the start of each trial.

---

## Quick Start

Copy this into the `"experiment"` section of `cfg.json`:

```json
"experiment": {
    "iti_duration": 3.0,

    "conditions": [
        {"label": "normal",  "transform_type": "identity",
         "trial_end_condition": "distance", "trial_distance": 50.0},
        {"label": "freeze",  "transform_type": "freeze",
         "trial_end_condition": "duration", "trial_duration": 10.0},
        {"label": "gain_2x", "transform_type": "gain",
         "transform_params": {"gain": 2.0},
         "trial_end_condition": "distance", "trial_distance": 50.0},
        {"label": "invert",  "transform_type": "invert",
         "trial_end_condition": "distance", "trial_distance": 50.0}
    ],

    "blocks": [
        {"name": "order_A",
         "sequence": ["normal", "freeze", "normal", "gain_2x"], "repeat": 5},
        {"name": "order_B",
         "sequence": ["invert", "normal", "freeze", "normal"], "repeat": 5}
    ]
}
```

Two rules keep this readable. **A condition says how its own trials end** —
there is no session-wide end rule to cross-reference. **A block says how many
trials it runs** — `len(sequence) × repeat`, with no global to contradict it.

Then run:

```bash
mouseportal                  # uses cfg.json (or: python runportal.py)
mouseportal -c my_exp.json   # uses a custom config
```

Press **Space** to start the session. The state machine advances automatically
through blocks and trials. Press **F1** to toggle the debug HUD, **Esc** to quit.

---

## Config Reference

### Session-wide parameters

Only what genuinely applies to the whole session. Trial-end rules are **not**
here — they belong to the conditions — and neither is session structure, which
lives entirely in `blocks`.

| Field | Type | Default | Description |
|---|---|---|---|
| `iti_duration` | float | `2.0` | Inter-trial interval in seconds |
| `iti_range` | [float, float] | `null` | When set, each ITI is drawn uniformly from `[min, max]` instead of using `iti_duration` |
| `random_seed` | int | today's date | Seed for every random draw in the session (ITI lengths and shuffled block orders). Unset, it becomes `YYYYMMDD` |

The transform belongs to the trial, not to the ITI: during the inter-trial
interval the corridor is always closed-loop (identity), whatever the trial's
transform was.

### Randomised timing and the seed

```json
"iti_duration": 30.0,
"iti_range": [15.0, 45.0],
"random_seed": 20260811
```

The seed actually used is written to `timing.json` under `experiment.random_seed`
and printed at startup, so a session started with `random_seed` unset can still
be repeated — put the recorded seed back in the config. Each drawn interval is
also logged as the `value` of that ITI's `ITI_START` event.

Left unset, the seed is **today's date as `YYYYMMDD`**. A date is legible in
the sidecar and in a lab notebook where a random 31-bit integer is not. The
consequence is worth stating: every session run on the same day with no
explicit seed draws the same ITI lengths and the same shuffled orders. Set
`random_seed` per subject when they need independent randomisation.

Plan expansion and ITI draws use two streams derived from that one seed, so
adding a trial to a block does not shift the ITI sequence.

### `conditions` — the palette of trial types

A list of condition objects. Each defines a label, a velocity transform, and
how its own trials end.

| Field | Type | Required | Description |
|---|---|---|---|
| `label` | string | **yes** | Unique name referenced by `blocks` and logged in the CSVs |
| `transform_type` | string | **yes** | Transform key (see table below) |
| `trial_end_condition` | string | **yes** | `"duration"`, `"distance"`, or `"manual"` |
| `trial_duration` | float | with `"duration"` | Trial length in seconds |
| `trial_distance` | float | with `"distance"` | Trial length in corridor units |
| `transform_params` | object | no | Parameters forwarded to the transform constructor |
| `expected_duration` | float | no | Planning estimate for `"distance"` / `"manual"` trials; see below |
| `iti_after` | bool | no (`true`) | `false` chains straight into the next condition |
| `iti_range` | [float, float] | no | Overrides the session draw for the interval this condition ends with |

**Every condition states its own end rule and the limit that goes with it.**
There is no session-wide default: a rule and its limit belong together, and
splitting them across two levels meant a trial's real behaviour could only be
worked out by reading both. The pairing is checked at load — `"duration"`
without a positive `trial_duration` is an error, as is `"distance"` on
`freeze` or `reverse`, which ignore the subject's input and so can never
reach a distance by their running.

#### `expected_duration`

A `"duration"` trial is its own length. A `"distance"` or `"manual"` trial has
no length until it happens, which matters to an orchestrator sizing a
recording. `expected_duration` is where you state the typical length for those
— it is **planning metadata only** and the state machine never reads it.
Conditions that omit it are left out of any run-length estimate rather than
being assigned a guessed one, and the estimate says how many trials it could
not account for.

### `blocks` — the session structure

A list, run top to bottom. Each entry is one block.

| Field | Type | Required | Description |
|---|---|---|---|
| `sequence` | [string] | **yes** | Condition labels making up one pass of the block, in order |
| `name` | string | no | Carried into `events.csv` and `trials.csv` so analysis can group by a meaningful label |
| `repeat` | int | no (`1`) | How many passes of `sequence` to run |
| `order` | string | no (`"fixed"`) | `"fixed"` runs the expanded list as written; `"shuffle"` permutes it with `random_seed` |

**This list is the only declaration of session structure.** The number of
blocks is its length; a block's trial count is `len(sequence) × repeat`. There
is no global trials-per-block, so blocks may differ in length and nothing can
disagree about how many trials there are.

```json
"blocks": [
    {"name": "reverse_train", "sequence": ["reverse"], "repeat": 40},
    {"name": "order_A", "sequence": ["normal", "freeze", "gain_2x", "invert"],
     "repeat": 3, "order": "shuffle"},
    {"name": "order_B", "sequence": ["invert", "gain_2x", "freeze", "normal"],
     "repeat": 3}
]
```

That is 40 + 12 + 12 = 64 trials in three blocks of different lengths.

#### `repeat` and `order`

`repeat` concatenates passes, so it never changes the *balance* of a block:
three repeats of four conditions is always twelve trials, three of each.
`order: "shuffle"` then permutes that expanded list, which keeps the counts
exact while randomising presentation order. Shuffling therefore cannot change
a block's total duration — only the sequence.

A shuffled order exists nowhere in the config; it is drawn from `random_seed`
at startup. The order actually run is written to `timing.json` under
`experiment.blocks`, so a finished session is readable without re-deriving
anything:

```json
"experiment": {
    "random_seed": 20260813,
    "total_trials": 64,
    "blocks": [
        {"name": "order_A", "order": "shuffle",
         "sequence": ["gain_2x", "normal", "freeze", "invert", "..."]}
    ]
}
```

Put that seed back in the config to reproduce both the shuffled orders and the
ITI draws exactly. The two are drawn from separate streams derived from the one
seed, so changing a block's length does not shift the ITI sequence.

#### What a block is, and is not

A block boundary emits `BLOCK_START` / `BLOCK_END` (carrying the block's name
as the event `value`) and resets the trial counter. It does **not** introduce a
pause, a rest period, or an interval of its own: the interval after a block's
last trial is that trial's ordinary ITI. Use blocks to give different parts of
a session different trial orders — that is what they are for.

#### Validation

Every label in every `sequence` must exist in `conditions`, every condition's
transform must build with the parameters given, condition labels must be
unique, and no key may be misspelled. All of it is checked when the config
loads, and every failure names what is wrong:

```
block 2 'order_B' references undefined condition(s) ['nrmal'].
    Defined conditions: ['freeze', 'gain_2x', 'invert', 'normal']
```

Nothing falls back to a default trial. A config that does not say what it
wants does not run.

---

## Input Gain

`camera.speed_scaling` converts the encoder's units into corridor units per
second, and applies to both hardware paths — `serial` (MousePortal owns the
port) and `network` (mesofield owns it and forwards samples over UDP). It is
what you calibrate against the animal's real running.

```json
"camera": {
    "height": 2.0,
    "speed_scaling": 1.0,
    "keyboard_speed": 20.0
}
```

`1.0` passes the encoder's speed through unchanged. `keyboard_speed` is the
corridor speed while an arrow key is held; it is already a corridor speed, so
`speed_scaling` does not apply to it — keyboard mode is for testing the
corridor, not for reproducing a calibrated treadmill gain.

In `samples.csv`, `velocity` is post-scaling and pre-transform, so
`effective_velocity / velocity` isolates the trial's transform.

---

## Available Transforms

| `transform_type` | Effect | Parameters | Example |
|---|---|---|---|
| `identity` | Passthrough | — | `{"label": "normal", "transform_type": "identity"}` |
| `gain` | Scale velocity | `gain` (float) | `{"label": "slow", "transform_type": "gain", "transform_params": {"gain": 0.5}}` |
| `freeze` | Force velocity to 0 | — | `{"label": "freeze", "transform_type": "freeze"}` |
| `offset` | Add constant drift | `offset` (float) | `{"label": "drift", "transform_type": "offset", "transform_params": {"offset": 5.0}}` |
| `invert` | Reverse direction | — | `{"label": "invert", "transform_type": "invert"}` |
| `reverse` | Move backward at a fixed speed, ignoring input | `speed` (float) | `{"label": "reverse", "transform_type": "reverse", "transform_params": {"speed": 20.0}}` |
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
- **`reverse`** — open-loop backward motion: the input is discarded and the
  camera moves backward at `speed` for the whole trial. Unlike `invert`, a
  stationary subject still sees the corridor reverse. Pair it with
  `"trial_end_condition": "duration"`; a distance rule would end the trial on
  the backward travel.

---

## Choosing a Trial-End Rule

Each condition picks one of three rules and supplies its limit. Conditions in
the same session may use different rules — that is the normal case, not an
exception.

### `duration` — a fixed number of seconds

The only rule an open-loop transform can use, since the subject's running does
not advance it:

```json
{
    "label": "freeze",
    "transform_type": "freeze",
    "trial_end_condition": "duration",
    "trial_duration": 10.0
}
```

Pairing `freeze` or `reverse` with `"distance"` is rejected at load rather than
left to stall the session.

### `distance` — a fixed corridor distance

Matches trial length to how far the subject actually ran. Give a gain-down
condition a longer target so it covers the same real distance as a normal
trial, and an `expected_duration` so the run length can still be estimated:

```json
{
    "label": "gain_half",
    "transform_type": "gain",
    "transform_params": {"gain": 0.5},
    "trial_end_condition": "distance",
    "trial_distance": 100.0,
    "expected_duration": 25.0
}
```

### `manual` — until the experimenter presses Space

```json
{
    "label": "probe",
    "transform_type": "identity",
    "trial_end_condition": "manual",
    "expected_duration": 60.0
}
```

Works inside an otherwise automated session: only this condition's trials wait
for a keypress.

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
`TRIAL_END`, `ITI_START`, `BLOCK_END`, `SESSION_COMPLETE`. `BLOCK_START` and
`BLOCK_END` carry the block's name as their `value`. The set is open —
`STIMULUS_ONSET`, `RESPONSE` and `REWARD` are reserved for paradigms that
emit them, and need no schema change.

`flip_timestamp` is `n/a` for events with no visual consequence (a trigger
keypress, for instance): there is no presentation time to report.

### `trials.csv`

`block`, `block_name`, `trial`, `condition`, `transform`, `transform_params`,
`start_timestamp`, `end_timestamp`, `duration`, `distance`, `end_rule`,
`n_frames`, `n_dropped`, `mean_velocity`, `mean_effective_velocity`.

`block_name` is the block's `name` from the config, or `n/a` when the block is
unnamed — it is what makes "which order was this trial in" a column rather
than a derivation.

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
    "iti_duration": 2.0,
    "conditions": [
        {"label": "normal", "transform_type": "identity",
         "trial_end_condition": "duration", "trial_duration": 30.0},
        {"label": "freeze", "transform_type": "freeze",
         "trial_end_condition": "duration", "trial_duration": 30.0},
        {"label": "noisy",  "transform_type": "noisy",
         "transform_params": {"sigma": 5.0},
         "trial_end_condition": "duration", "trial_duration": 30.0}
    ],
    "blocks": [
        {"sequence": ["normal", "freeze", "noisy"]}
    ]
}
```

### Many repeats of one condition

40 reverse trials, each 3 s, separated by a jittered 8–12 s of normal
closed-loop running. The transform belongs to the trial, so the ITI between
reverses is ordinary corridor movement.

```json
"experiment": {
    "iti_range": [8.0, 12.0],
    "conditions": [
        {"label": "reverse", "transform_type": "reverse",
         "transform_params": {"speed": 20.0},
         "trial_end_condition": "duration", "trial_duration": 3.0}
    ],
    "blocks": [
        {"name": "reverse_train", "sequence": ["reverse"], "repeat": 40}
    ]
}
```

One block of 40 trials, not 40 blocks of one: blocks introduce no interval of
their own, so the two run identically, but 40 blocks would write `trial=1` on
all forty rows of `trials.csv` and leave the trial index carrying no
information.

### Two counterbalanced orders

```json
"conditions": [
    {"label": "gain_0.5", "transform_type": "gain", "transform_params": {"gain": 0.5},
     "trial_end_condition": "duration", "trial_duration": 30.0},
    {"label": "gain_1.0", "transform_type": "identity",
     "trial_end_condition": "duration", "trial_duration": 30.0},
    {"label": "gain_1.5", "transform_type": "gain", "transform_params": {"gain": 1.5},
     "trial_end_condition": "duration", "trial_duration": 30.0},
    {"label": "gain_2.0", "transform_type": "gain", "transform_params": {"gain": 2.0},
     "trial_end_condition": "duration", "trial_duration": 30.0}
],
"blocks": [
    {"name": "ascending",  "sequence": ["gain_0.5", "gain_1.0", "gain_1.5", "gain_2.0"], "repeat": 3},
    {"name": "descending", "sequence": ["gain_2.0", "gain_1.5", "gain_1.0", "gain_0.5"], "repeat": 3},
    {"name": "random",     "sequence": ["gain_0.5", "gain_1.0", "gain_1.5", "gain_2.0"],
     "repeat": 3, "order": "shuffle"}
]
```

Each block runs 12 trials, three of each gain. `trials.csv` carries the block
name, so the order effect is a `groupby("block_name")` rather than a lookup
against the config.

### Delay detection threshold

```json
"conditions": [
    {"label": "normal",  "transform_type": "identity",
     "trial_end_condition": "duration", "trial_duration": 20.0},
    {"label": "lag_50",  "transform_type": "delay", "transform_params": {"delay_sec": 0.05},
     "trial_end_condition": "duration", "trial_duration": 20.0},
    {"label": "lag_100", "transform_type": "delay", "transform_params": {"delay_sec": 0.1},
     "trial_end_condition": "duration", "trial_duration": 20.0},
    {"label": "lag_200", "transform_type": "delay", "transform_params": {"delay_sec": 0.2},
     "trial_end_condition": "duration", "trial_duration": 20.0},
    {"label": "lag_500", "transform_type": "delay", "transform_params": {"delay_sec": 0.5},
     "trial_end_condition": "duration", "trial_duration": 20.0}
]
```

Put these in a shuffled block so lag order does not confound the threshold:

```json
"blocks": [
    {"name": "lag_probe",
     "sequence": ["normal", "lag_50", "lag_100", "lag_200", "lag_500"],
     "repeat": 5, "order": "shuffle"}
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
