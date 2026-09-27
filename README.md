**English** | [简体中文](README-ch.md)

# WaveShare PiRacer Pro - Chalmers Folkrace Autonomous Driving Control Program

This project is an autonomous line-following and road perception control system designed specifically for the **WaveShare PiRacer Pro AI Kit** to compete in the **Chalmers Robot Folkrace competition**. The system is based on **OpenCV2**, **NumPy**, **Picamera2**, and **PiRacerPro** hardware drivers, with reserved expansion interfaces for **side infrared ranging/ultrasonic obstacle avoidance sensors**.

---

## 📁 Project Architecture

- **`config.py`**: Core parameter configuration file (including camera resolution, HSV track thresholds, ROI cropping regions, PID steering parameters, dynamic speed limits, and sensor GPIO pin mappings).
- **`camera.py`**: Camera abstraction wrapper (prioritizes Raspberry Pi official `Picamera2` capture, supports local OpenCV camera and synthetic frame debugging fallback without hardware).
- **`vision.py`**: Computer vision track perception module (multi-layer horizontal slice weighted centroid scanning, adaptive/HSV track extraction, lookahead distance calculation).
- **`controller.py`**: PID steering controller and PiRacerPro chassis control wrapper (supports corner adaptive deceleration, out-of-focus deceleration line tracking, and emergency power cutoff protection).
- **`sensors.py`**: Left and right side ultrasonic (HC-SR04) and infrared obstacle avoidance sensor management module (wall-hugging thrust correction and emergency braking).
- **`main.py`**: System main control loop entry (supports frame rate control, keyboard/system signal safe interrupt exit, and debug window visualization).
- **`streamer.py`**: Standard-library MJPEG web streamer, plus the HTTP control API for the debug console (no extra pip dependencies).
- **`webcontrol.py`**: Remote debug state machine and the tunable-parameter whitelist. Thread-safe, touches no hardware, and is the single authority on permissions and value validation.
- **`webui.py`**: The debug console page (HTML/CSS/JS). Renders only the tabs that the launch flags permit.

---

## 🚀 Raspberry Pi Environment Installation and Dependencies

Run on PiRacer Pro (Raspberry Pi OS Bookworm / Bullseye):

```bash
# 1. Update system and install system-level dependencies
sudo apt update
sudo apt install -y python3-pip python3-opencv python3-numpy python3-rpi.gpio python3-smbus

# 2. Install Picamera2 (usually pre-installed on Bookworm images)
sudo apt install -y python3-picamera2

# 3. Install chassis and servo driver libraries (choose one or install both, program auto-detects)
pip3 install piracer-py
# Or use Adafruit ServoKit to drive PCA9685
pip3 install adafruit-circuitpython-servokit
```

---

## 🔧 Hardware Self-Check and Diagnostics (Important)

Before starting autonomous line tracking, please run the hardware self-check script first (**Note: Please suspend the car wheels off the ground before testing to prevent runaway**):

```bash
python3 test_hardware.py
```

This script will sequentially test:
1. **I2C bus and PCA9685 chip communication (0x40)**
2. **ESC electronic speed controller center self-check unlock sequence (1.5s)**
3. **Steering servo sweep (center -> left turn -> center -> right turn -> center)**
4. **Rear drive motor rotation (forward 0.28 -> brake -> reverse -0.25 -> stop)**
5. **Picamera2 camera image capture**

> The full deployment, bench-test, permission-gate and pre-race checklist is in
> **[MANUAL-CHECKS-en.md](MANUAL-CHECKS-en.md)** (every item needs a human).

---

## 🎮 Running Modes

### 1. LAN Web Real-time Streaming Mode (Recommended: View directly in computer/mobile browser)
Start streaming on Raspberry Pi:
```bash
python3 main.py --stream
```
Then open in computer or mobile browser (on same Wi-Fi as Raspberry Pi):
```text
http://<RaspberryPiIP>:8080
```
> The page will display real-time car camera front view, track centerline recognition trajectory, and real-time telemetry data (FPS, real-time steering angle Steer, real-time throttle Thr).
> Customizable port: `python3 main.py --stream --port 8080 --throttle 0.32`

### 2. Competition Real Car Running (Maximum speed no-interface mode, highest frame rate)
```bash
python3 main.py --throttle 0.32
```

### 3. Local Desktop GUI Debug Mode (Requires HDMI screen or X11 forwarding)
```bash
python3 main.py --display
```

### 4. Enable Side Ultrasonic/Infrared Sensor Obstacle Avoidance
```bash
python3 main.py --stream --enable-sensors
```

### 5. Switch Track Perception Mode
- `edge_contours` (default, dual-side track wall/boundary detection and adaptive corridor centerline tracking)
- `lane_line` (bright guideline/white line mode, supports HSV and adaptive highlight segmentation)
- `color_mask` (dark track/dark asphalt mode)

```bash
python3 main.py --mode lane_line --throttle 0.35
```

### 6. Web Debug Console — Live Tuning and Manual Drive (Testing Only)

Both control tabs are opt-in from the terminal. Anyone on the same LAN can open the
page, so what appears in the browser is decided by the command that started the
program on the Raspberry Pi — opening the page is never enough to take control.

| Command | Page shows | Car does |
|---|---|---|
| `python3 main.py --stream` | Camera feed only | Autonomous line following (unchanged) |
| `python3 main.py --stream --allow-tuning` | Camera feed + **Tuning** tab | Autonomous; parameters change live |
| `python3 main.py --stream --allow-manual` | Camera feed + **Tuning** + **Manual Drive** | Starts **PAUSED** and waits for an operator |

`--allow-manual` implies `--allow-tuning`.

**Manual drive flow**

```text
start ──► PAUSED (car held)
   ├─ hold ARM for 2 s ──► MANUAL (deadman: stops if commands stop arriving)
   │     └─ STOP ──► PAUSED
   └─ START AUTONOMOUS ──► AUTO
         └─ STOP ──► PAUSED
```

After a stop you can hold ARM again to go back to manual; no restart needed.
Press `Ctrl-C` in the terminal to quit.

**Safety properties**

- **Armed is not moving.** Arming enters MANUAL at zero throttle and the car stays
  still until a drive command actually arrives.
- **Deadman.** If no command arrives for 0.8 s, the car is commanded to a full stop.
  It stays in MANUAL and never resumes autonomous driving on its own.
- **Server-side clamping.** Operator input is clamped to `RemoteConfig.max_manual_throttle`
  (0.40), deliberately below the autonomous `max_throttle` (0.50): manual driving can
  never outrun autonomous driving.
- **The emergency brake always applies.** In manual mode the side-wall steering
  correction is disabled — the operator is the steering authority — but a proximity
  emergency stop still overrides every mode.
- **The video overlay states the mode.** Anything other than autonomous draws a
  banner across the top of the stream: `MANUAL CONTROL - NOT AUTONOMOUS`, `PAUSED`,
  or `DEADMAN - COMMANDS LOST`. An autonomous run draws nothing.
- **A closed page stops the car.** Switching away from the tab zeroes both axes, and
  closing the page sends a stop. It never hands the car back to autonomous control.
- **Cross-origin requests cannot reach the API.** Drive commands must be POSTed as
  `application/json`, which forces a CORS preflight that this server never answers.
  Do not add CORS headers to it.

**Deliberately not exposed for tuning:** `invert_steering`, `invert_throttle`,
`show_debug_window`, `esc_arm_time`, and every `SensorConfig` threshold. Flipping an
invert flag while driving means full opposite lock or full reverse, and the sensor
thresholds *are* the collision-avoidance layer.

**A competition run uses none of these flags.** `python3 main.py --throttle 0.32` is
the race command, and it behaves exactly as it did before this feature existed.

---

## 🛠 Tuning Guide (For Chalmers Folkrace Track)

Quick adjustments for specific venues in `config.py`:

1. **Steering Response and Corner Oscillation**:
   - If the car is slow to enter corners, appropriately increase `ControlConfig.kp` (e.g., from `0.65` to `0.80`).
   - If there is left-right snake-like oscillation on straight roads, appropriately increase `ControlConfig.kd` (e.g., to `0.15~0.20`), and decrease `kp`.
2. **Straight Line Acceleration and Corner Deceleration**:
   - `base_throttle`: Cruise speed (default `0.28`).
   - `turn_slowdown_factor`: Corner deceleration factor (default `0.5`), the larger the steering angle, the lower the speed, to prevent corner push-over rollover.
3. **Visual Perception Region (ROI)**:
   - `roi_top_ratio`: Default `0.45` (ignore ceiling and distant track background, focus on road surface ahead of car front).
   - `roi_bottom_ratio`: Default `0.95` (ignore car front bumper shadow).
4. **Left/Right Sensor Obstacle Avoidance Connection**:
   - Ultrasonic left default pins: TRIG `GPIO 23`, ECHO `GPIO 24`
   - Ultrasonic right default pins: TRIG `GPIO 27`, ECHO `GPIO 22`
   - Infrared sensor default pins: left `GPIO 17`, right `GPIO 18`
5. **Live Tuning from the Browser** (`--allow-tuning`):
   The **Tuning** tab edits the same values as `config.py`, applied immediately — the
   car keeps following the line while you change them. This is the fastest way to find
   PID gains on the actual track instead of guessing in the pits; the telemetry strip
   above the video shows the effect of each change right away.
   - Values are validated on the server, so a slider can never leave the car in a state
     it cannot drive out of. Out-of-range values are refused, and an inverted ROI (top
     below bottom, which would crop the image to nothing and send the car straight on
     with no steering correction) is rejected as a whole batch.
   - **Reset PID State** clears the integrator and derivative history after a big gain
     change, so old accumulated error does not carry over.
   - **Copy as config.py** copies the current values so you can paste them back into
     `config.py`. Tuning lives in memory only and is lost when the program exits.

# Contributors
- Pengpung
- Duckystew