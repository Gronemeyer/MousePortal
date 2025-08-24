# Mouse Portal <img src="https://github.com/user-attachments/assets/3db5432d-7a35-40df-a91f-4387e241ee24" width="120" height="70">

Renders infinite corridor using Panda3D for behavioral neuroscience research

# Current Features:
- JSON Parameterization
- Data logging to CSV
- Customizable textures for corridor walls
- Command interface via STDIN/STDOUT
- Panda3D FSM for trial control
- infinite rendering algorithm
- Event logging with send/receive timestamps
- Mappable input (keyboard)

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


