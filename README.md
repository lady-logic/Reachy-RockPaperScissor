# Reachy Mini — Rock Paper Scissors

![Reachy Mini](reachy_mini_conversation_app/docs/assets/reachy_mini_dance.gif)

Play rock-paper-scissors against your Reachy Mini robot. Reachy throws with its head and antennas and reacts to the outcome with sound and movement.

---

## Requirements

- [Reachy Mini desktop app](https://www.pollen-robotics.com) (daemon v1.11.0)
- Python 3.10+
- Webcam (for `--laptop-camera` mode)

---

## Setup

```bash
git clone https://github.com/lady-logic/Reachy-RockPaperScissor.git
cd Reachy-RockPaperScissor
python -m venv venv
venv\Scripts\activate        # Windows
pip install -r requirements.txt
```

---

## Run

Start the Reachy Mini daemon first (via the desktop app or manually), then:

```bash
python -m reachy_mini_rps.main
```

### Useful flags

| Flag | Description |
|---|---|
| `--laptop-camera` | Use your laptop webcam instead of the robot camera |
| `--no-mic` | Disable voice activation — start rounds via the web UI |
| `--local-sound` | Play audio through your PC speakers instead of the robot |

### Simulator / Windows mode (no physical robot)

```bash
python -m reachy_mini_rps.main --laptop-camera --no-mic --local-sound
```

Start a round via the web UI at `http://localhost:8042` or:

```bash
curl -X POST http://localhost:8042/play
```

---

## Windows compatibility (this fork)

The original repo targets macOS (AVFoundation, GStreamer). This fork adds Windows support:

- `laptop_camera.py` — rewritten with OpenCV + DirectShow instead of AVFoundation/GStreamer
- `--no-mic` flag — skips audio input when the daemon runs without media
- `--local-sound` flag — plays WAV clips via `winsound` instead of the robot speaker
