# Mouse Portal <img src="https://github.com/user-attachments/assets/3db5432d-7a35-40df-a91f-4387e241ee24" width="120" height="70">

Renders infinite corridor using Panda3D for behavioral neuroscience research

## Current Features

- JSON-configurable corridor with customizable textures
- Infinite Panda3D corridor rendering with keyboard dev controls
- CSV data and event logging with timestamped metadata
- Dual command interfaces via STDIN and TCP socket
- Trial controllers for closed-loop treadmill and scripted open-loop runs
- Parent PyQt6 GUI for launching, monitoring, and marking events

## Setup Instructions

1. **Clone the Repository:**

   ```bash
   git clone https://github.com/Gronemeyer/mouseportal.git
   cd mouseportal
   ```

2. **Create and Activate a Conda Environment:**

   ```bash
   conda create --name mouseportal python=3.11
   conda activate mouseportal
   ```

3. **With an Activated Virtual Environment:**

   ```bash
   pip install panda3d
   ```

## Development Mode

Run `python runportal.py --dev` to test without a treadmill. Movement uses the arrow keys. When running in this mode the window displays the current FSM state in the upper left corner.

## Parent Process prototype

Run `python parent_test.py` to open a PyQt6 GUI. The table at the top lists parameters from `cfg.json`; edit values before launching. Use **Launch Portal** to start `runportal.py --dev` with the edited settings and **End Portal** to shut it down.
The **Start**, **Stop**, and **Mark Event** buttons send experiment commands while the text area shows live output from the child process. Commands now include a timestamp so runportal can compute send/receive offsets.

## Socket Control

- `runportal.py` exposes a TCP server on `127.0.0.1:8765` once Panda3D is running.
- Messages are newline-delimited JSON dictionaries; every response includes `server_time` for clock sync.
- Incoming commands should include `command` and optional metadata such as `trial_type` or `segments`.
- Status, event, and acknowledgement packets echo trial metadata so parents can stay in sync.

Example command payload:

```json
{"command": "start_trial", "trial_id": "trial_12", "trial_type": "open_loop"}
```

## Trial Modes

- `start_trial` requires `trial_type` set to `closed_loop` or `open_loop`.
- Closed-loop trials follow treadmill velocity using the configured gain and bias.
- Open-loop trials run a scripted sequence of gain/bias segments; treadmill velocity is ignored.
- Provide a `segments` list with the command or rely on the default sequence from `cfg.json`.

Open-loop segment example:

```json
[
   {"duration": 5.0, "gain": 1.0},
   {"duration": 2.0, "gain": -0.3, "bias": 0.4},
   {"duration": 4.0, "bias": 0.6},
   {"duration": 1.5, "gain": 0.0}
]
```

Each segment supplies a duration (seconds) plus an optional `gain` multiplier and additive `bias`. Gains or biases omitted from the first segment default to the current closed-loop settings; omissions in later segments inherit the previous segment’s values. Include `{"loop": true}` in the command payload to repeat the list until the trial is stopped.

Add `default_trial_type` or an `open_loop_schedule` array to `cfg.json` to change the defaults used when the portal launches.


