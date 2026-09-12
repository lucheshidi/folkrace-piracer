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
- `lane_line` (bright guide line/white line mode, supports HSV and adaptive highlight segmentation)
- `color_mask` (dark track/dark asphalt mode)

```bash
python3 main.py --mode lane_line --throttle 0.35
```

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

# Contributors
- Pengpung
- Duckystew
