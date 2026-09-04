"""
Vehicle and Motion Control module for PiRacer Pro.
Includes PID controller for steering, dynamic speed management,
and hardware abstraction for PiRacerPro chassis.
"""

import logging
import time
from typing import Tuple
import numpy as np

from config import ControlConfig

try:
    from piracer.vehicles import PiRacerPro
    PIRACER_AVAILABLE = True
except ImportError:
    PIRACER_AVAILABLE = False


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
    """Hardware controller for Waveshare PiRacer Pro."""

    def __init__(self, config: ControlConfig):
        self.config = config
        self.pid = PIDController(config.kp, config.ki, config.kd)
        self.piracer = None
        self.current_steering = 0.0
        self.current_throttle = 0.0

    def start(self):
        """Initialize PiRacer Pro hardware."""
        if PIRACER_AVAILABLE:
            try:
                self.piracer = PiRacerPro()
                self.stop()
                logging.info("PiRacerPro hardware initialized successfully.")
            except Exception as e:
                logging.error(f"Failed to initialize PiRacerPro hardware: {e}")
                self.piracer = None
        else:
            logging.warning("piracer package not available. Running in simulated vehicle mode.")

    def compute_control(self, error: float, track_detected: bool) -> Tuple[float, float]:
        """
        Compute steering and throttle based on perception error.

        Returns:
            steering (float): [-1.0, 1.0]
            throttle (float): [0.0, 1.0]
        """
        if not track_detected:
            # When track is temporarily lost, hold previous slight steer and reduce speed
            steering = float(np.clip(self.current_steering * 0.8, self.config.min_steering, self.config.max_steering))
            throttle = self.config.min_throttle * 0.6
            return steering, throttle

        # Compute PID steering
        raw_steering = self.pid.compute(error) + self.config.steering_trim
        steering = float(np.clip(raw_steering, self.config.min_steering, self.config.max_steering))

        # Dynamic throttle: reduce speed when turning sharply
        turn_severity = abs(steering)
        speed_reduction = turn_severity * self.config.turn_slowdown_factor
        throttle = self.config.base_throttle * (1.0 - speed_reduction)
        throttle = float(np.clip(throttle, self.config.min_throttle, self.config.max_throttle))

        return steering, throttle

    def set_drive(self, steering: float, throttle: float):
        """Apply steering and throttle to the vehicle."""
        self.current_steering = float(np.clip(steering, -1.0, 1.0))
        self.current_throttle = float(np.clip(throttle, -1.0, 1.0))

        if self.piracer is not None:
            try:
                # Support different PiRacer library method conventions
                if hasattr(self.piracer, "set_steering_percent"):
                    self.piracer.set_steering_percent(self.current_steering)
                elif hasattr(self.piracer, "steering"):
                    self.piracer.steering = self.current_steering

                if hasattr(self.piracer, "set_throttle_percent"):
                    self.piracer.set_throttle_percent(self.current_throttle)
                elif hasattr(self.piracer, "throttle"):
                    self.piracer.throttle = self.current_throttle
            except Exception as e:
                logging.error(f"Error applying vehicle drive command: {e}")

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
                logging.error(f"Error during vehicle stop: {e}")
        logging.info("Vehicle stopped safely.")
