"""
Configuration file for PiRacer Pro Folkrace Autonomous Vehicle.
Contains all hardware settings, PID parameters, vision thresholds, and sensor configs.
"""

from dataclasses import dataclass, field


@dataclass
class CameraConfig:
    # Camera resolution and framerate
    # OV5647 native fast binned mode is 640x480 @ ~60fps
    width: int = 640
    height: int = 460
    framerate: int = 30
    format: str = "RGB888"  # or 'BGR888'


@dataclass
class VisionConfig:
    # Region of Interest (ROI) - vertical cropping from bottom (0.0: top, 1.0: bottom)
    roi_top_ratio: float = 0.45  # Focus on the track in front, ignore ceiling/horizon
    roi_bottom_ratio: float = 0.95

    # Track detection mode: 'lane_line' (white/yellow line), 'color_mask', or 'edge_contours'
    detection_mode: str = "edge_contours"

    # Color thresholding parameters (HSV) for track / line following
    # Default white line threshold in HSV
    hsv_white_lower: tuple = (0, 0, 180)
    hsv_white_upper: tuple = (180, 50, 255)

    # Default dark road / track threshold (if tracking dark track on light surface)
    hsv_dark_lower: tuple = (0, 0, 0)
    hsv_dark_upper: tuple = (180, 255, 80)

    # Canny edge detection thresholds
    canny_threshold1: int = 50
    canny_threshold2: int = 150

    # Number of scanlines / slices for center extraction
    num_scan_slices: int = 5

    # Debug image visualization flag
    show_debug_window: bool = False


@dataclass
class ControlConfig:
    # control
    kp = 0.65
    ki = 0
    kd = 0.12
    base_throttle = 0.3
    max_throttle = 0.5
    min_throttle = 0.22
    throttle_deadband = 0.18
    turn_slowdown_factor = 0.06
    reverse_throttle = -0.25
    steering_trim = 0
    esc_arm_time = 1.0
    invert_steering = False
    invert_throttle = False
    steering_sensitivity = 1.0
    min_steering = -1.0
    max_steering = 1.0

    # vision
    roi_top_ratio = 0.45
    roi_bottom_ratio = 0.95
    detection_mode = "edge_contours"
    num_scan_slices = 5
    canny_threshold1 = 50
    canny_threshold2 = 150


@dataclass
class SensorConfig:
    # Enable external distance sensors (IR / Ultrasonic)
    enable_sensors: bool = False

    # Left & Right Ultrasonic sensor pin definitions (BCM numbering)
    left_trig_pin: int = 23
    left_echo_pin: int = 24
    right_trig_pin: int = 27
    right_echo_pin: int = 22

    # Left & Right Infrared digital/analog sensor pins
    left_ir_pin: int = 17
    right_ir_pin: int = 18

    # Obstacle / Wall detection thresholds (in centimeters)
    emergency_stop_dist_cm: float = 15.0
    side_warning_dist_cm: float = 25.0

    # Interval (seconds) between ultrasonic sweeps in the background sampling thread.
    # Must exceed the worst-case blocking time of one sweep, otherwise readings go stale.
    ultrasonic_sample_interval: float = 0.05


@dataclass
class StreamConfig:
    # Web MJPEG Video Streamer settings (for viewing live camera feed in browser on PC)
    enable_stream: bool = False
    host: str = "0.0.0.0"
    port: int = 8080
    jpeg_quality: int = 70


@dataclass
class RemoteConfig:
    """
    Web remote control settings for debugging (live tuning + manual driving).

    Both gates default to False. The web page is served to anyone on the LAN, so
    the terminal command that starts the program is what decides whether a control
    tab exists at all -- opening the page is never enough to take control of the
    car. A competition run must stay autonomous, so neither gate belongs in the
    race-day command line.
    """
    # Terminal-side gates (--allow-tuning / --allow-manual). Without them the web
    # page renders the video feed and telemetry only.
    allow_tuning: bool = False   # Live parameter tuning; the car stays autonomous.
    allow_manual: bool = False   # Manual drive tab; implies allow_tuning.

    # Deadman: if no drive command arrives within this window while armed, the car
    # is commanded to a full stop. Mandatory safety net -- do not disable.
    deadman_timeout_s: float = 0.8

    # Hard limits applied to operator input (server side, defence in depth).
    # max_manual_throttle deliberately sits below ControlConfig.max_throttle (0.50):
    # manual driving must never be faster than autonomous driving.
    max_manual_throttle: float = 0.40
    max_manual_reverse: float = -0.25
    max_manual_steering: float = 1.0


@dataclass
class AppConfig:
    camera: CameraConfig = field(default_factory=CameraConfig)
    vision: VisionConfig = field(default_factory=VisionConfig)
    control: ControlConfig = field(default_factory=ControlConfig)
    sensor: SensorConfig = field(default_factory=SensorConfig)
    stream: StreamConfig = field(default_factory=StreamConfig)
    remote: RemoteConfig = field(default_factory=RemoteConfig)

    # Log level and loop target rate
    target_loop_hz: int = 30

    # Robustness: abort the main loop (and stop the vehicle) after this many
    # consecutive frame-processing errors. A single bad frame is skipped instead.
    max_consecutive_frame_errors: int = 10
