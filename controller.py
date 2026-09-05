"""
Vehicle and Motion Control module for PiRacer Pro.
Includes PID controller for steering, dynamic speed management,
ESC neutral arming sequence, and hardware abstraction for PiRacerPro / PCA9685 chassis.
"""

import logging
import time
from typing import Tuple, Optional
import numpy as np

from config import ControlConfig

# Try importing official piracer package
try:
    from piracer.vehicles import PiRacerPro
    PIRACER_AVAILABLE = True
except ImportError:
    PIRACER_AVAILABLE = False

# Try importing Adafruit PCA9685 / ServoKit as fallback
try:
    from adafruit_servokit import ServoKit
    SERVOKIT_AVAILABLE = True
except ImportError:
    SERVOKIT_AVAILABLE = False


class PIDController:
    """PID Controller for steering regulation."""

    def __init__(self, kp: float, ki: float, kd: float):
        self.kp = kp
        self.ki = ki
        self.kd = kd
        self.prev_error = 0.0
        self.integral = 0.0
        self.last_time = time.time()

    def reset(self):
        self.prev_error = 0.0
        self.integral = 0.0
        self.last_time = time.time()

    def compute(self, error: float) -> float:
        """Compute PID output steering command given target error [-1.0, 1.0]."""
        current_time = time.time()
        dt = current_time - self.last_time
        if dt <= 0.0:
            dt = 1e-3

        # Proportional term
        p_term = self.kp * error

        # Integral term with anti-windup clamping
        self.integral += error * dt
        self.integral = float(np.clip(self.integral, -1.0, 1.0))
        i_term = self.ki * self.integral

        # Derivative term
        d_term = self.kd * ((error - self.prev_error) / dt)

        # Output calculation
        output = p_term + i_term + d_term

        self.prev_error = error
        self.last_time = current_time

        return float(output)


class VehicleController:
    """Hardware controller for Waveshare PiRacer Pro with multi-backend fallback."""

    def __init__(self, config: ControlConfig):
        self.config = config
        self.pid = PIDController(config.kp, config.ki, config.kd)
        self.backend_type: str = "simulation"
        self.piracer = None
        self.servokit = None
        self.current_steering = 0.0
        self.current_throttle = 0.0

    def start(self):
        """Initialize PiRacer Pro hardware backend and arm ESC."""
        # 1. Primary backend: piracer-py
        if PIRACER_AVAILABLE:
            try:
                self.piracer = PiRacerPro()
                self.backend_type = "piracer-py (PiRacerPro)"
                logging.info("Hardware Backend: Successfully connected via piracer-py (PiRacerPro).")
            except Exception as e:
                logging.warning(f"Could not connect via piracer-py: {e}. Trying secondary backend...")
                self.piracer = None

        # 2. Secondary backend: adafruit-circuitpython-servokit (Direct PCA9685)
        if self.piracer is None and SERVOKIT_AVAILABLE:
            try:
                # Standard Waveshare PiRacer Pro uses PCA9685 with 16 channels on I2C bus 1 (0x40)
                self.servokit = ServoKit(channels=16)
                # Channel 0: Steering Servo (pulse range ~1000us - 2000us, centered at 1500us)
                self.servokit.servo[0].set_pulse_width_range(1000, 2000)
                # Channel 1: Throttle ESC (Continuous Servo / PWM)
                self.servokit.continuous_servo[1].set_pulse_width_range(1000, 2000)
                self.backend_type = "adafruit-servokit (PCA9685)"
                logging.info("Hardware Backend: Connected via Adafruit ServoKit (PCA9685).")
            except Exception as e:
                logging.warning(f"Could not connect via ServoKit: {e}")
                self.servokit = None

        if self.piracer is None and self.servokit is None:
            self.backend_type = "simulation"
            logging.warning("=" * 60)
            logging.warning("⚠️  NO PHYSICAL PIRACER HARDWARE DETECTED!")
            logging.warning("   Running in SIMULATION MODE (commands logged only).")
            logging.warning("   To drive real car, ensure I2C is enabled (`sudo raspi-config`)")
            logging.warning("   and `pip install piracer-py` or `pip install adafruit-circuitpython-servokit`.")
            logging.warning("=" * 60)

        # 3. ESC Neutral Arming Sequence
        # Hobbywing and RC ESCs require a neutral throttle pulse (0.0) for ~1s on startup to arm!
        logging.info(f"Arming ESC at neutral for {self.config.esc_arm_time:.1f}s...")
        self.stop()
        time.sleep(self.config.esc_arm_time)
        logging.info("Vehicle controller ready and armed.")

    def compute_control(self, error: float, track_detected: bool) -> Tuple[float, float]:
        """
        Compute steering and throttle based on perception error.

        Returns:
            steering (float): [-1.0, 1.0]
            throttle (float): [0.0, 1.0]
        """
        if not track_detected:
            # Track lost: maintain previous steering direction with decay, keep searching speed
            steering = float(np.clip(self.current_steering * 0.9, self.config.min_steering, self.config.max_steering))
            # Keep throttle above deadband so vehicle doesn't stall completely during brief blinks
            throttle = max(self.config.min_throttle, self.config.throttle_deadband)
            return steering, throttle

        # Compute PID steering
        raw_steering = self.pid.compute(error) + self.config.steering_trim
        if self.config.invert_steering:
            raw_steering = -raw_steering
        steering = float(np.clip(raw_steering, self.config.min_steering, self.config.max_steering))

        # Dynamic throttle: reduce speed when turning sharply
        turn_severity = abs(steering)
        speed_reduction = turn_severity * self.config.turn_slowdown_factor
        raw_throttle = self.config.base_throttle * (1.0 - speed_reduction)

        if self.config.invert_throttle:
            raw_throttle = -raw_throttle

        # Throttle deadband compensation: ensure motor receives enough voltage to start turning
        if raw_throttle > 0:
            throttle = float(np.clip(max(raw_throttle, self.config.throttle_deadband),
                                     self.config.min_throttle, self.config.max_throttle))
        else:
            throttle = float(np.clip(raw_throttle, self.config.reverse_throttle, 0.0))

        return steering, throttle

    def set_drive(self, steering: float, throttle: float):
        """Apply steering and throttle to the vehicle."""
        self.current_steering = float(np.clip(steering, -1.0, 1.0))
        self.current_throttle = float(np.clip(throttle, -1.0, 1.0))

        # 1. piracer-py backend
        if self.piracer is not None:
            try:
                if hasattr(self.piracer, "set_steering_percent"):
                    self.piracer.set_steering_percent(self.current_steering)
                elif hasattr(self.piracer, "steering"):
                    self.piracer.steering = self.current_steering

                if hasattr(self.piracer, "set_throttle_percent"):
                    self.piracer.set_throttle_percent(self.current_throttle)
                elif hasattr(self.piracer, "throttle"):
                    self.piracer.throttle = self.current_throttle
            except Exception as e:
                logging.error(f"Error applying drive command via piracer-py: {e}")

        # 2. ServoKit (PCA9685) backend
        elif self.servokit is not None:
            try:
                # Servo angle: map [-1.0, 1.0] to [0.0, 180.0] degrees (center 90)
                servo_angle = (self.current_steering + 1.0) * 90.0
                servo_angle = float(np.clip(servo_angle, 0.0, 180.0))
                self.servokit.servo[0].angle = servo_angle

                # ESC throttle: continuous servo throttle [-1.0, 1.0]
                self.servokit.continuous_servo[1].throttle = self.current_throttle
            except Exception as e:
                logging.error(f"Error applying drive command via ServoKit: {e}")

    def stop(self):
        """Emergency stop: reset steering and kill throttle."""
        self.current_steering = 0.0
        self.current_throttle = 0.0

        if self.piracer is not None:
            try:
                if hasattr(self.piracer, "set_steering_percent"):
                    self.piracer.set_steering_percent(0.0)
                if hasattr(self.piracer, "set_throttle_percent"):
                    self.piracer.set_throttle_percent(0.0)
            except Exception as e:
                logging.error(f"Error during piracer stop: {e}")

        elif self.servokit is not None:
            try:
                self.servokit.servo[0].angle = 90.0
                self.servokit.continuous_servo[1].throttle = 0.0
            except Exception as e:
                logging.error(f"Error during ServoKit stop: {e}")

        logging.info("Vehicle stopped safely.")
