"""
Configuration file for PiRacer Pro Folkrace Autonomous Vehicle.
Contains all hardware settings, PID parameters, vision thresholds, and sensor configs.
"""

from dataclasses import dataclass, field


@dataclass
class CameraConfig:
    # Camera resolution and framerate
    # Lower resolution ensures higher processing FPS on Raspberry Pi
    width: int = 640
    height: int = 360
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
    # Steering PID parameters
    kp: float = 0.65
    ki: float = 0.00
    kd: float = 0.12

    # Steering limits [-1.0, 1.0]
    max_steering: float = 1.0
    min_steering: float = -1.0
    steering_trim: float = 0.0       # Hardware zero-point calibration trim
    invert_steering: bool = False    # Invert steering direction if servo turns opposite

    # Throttle / Speed settings
    base_throttle: float = 0.30      # Cruising speed (0.0 to 1.0)
    max_throttle: float = 0.50       # Straight line boost
    min_throttle: float = 0.22       # Minimum forward throttle during corners
    throttle_deadband: float = 0.18  # Minimum ESC throttle to overcome motor static friction
    reverse_throttle: float = -0.25  # Reverse speed for unstuck
    invert_throttle: bool = False    # Invert throttle direction

    # Dynamic speed scaling: reduce speed when steering angle is large
    turn_slowdown_factor: float = 0.4
    
    # ESC arming delay (in seconds) on startup
    esc_arm_time: float = 1.5


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


@dataclass
class AppConfig:
    camera: CameraConfig = field(default_factory=CameraConfig)
    vision: VisionConfig = field(default_factory=VisionConfig)
    control: ControlConfig = field(default_factory=ControlConfig)
    sensor: SensorConfig = field(default_factory=SensorConfig)

    # Log level and loop target rate
    target_loop_hz: int = 30
