"""
Sensor extension module for PiRacer Pro.
Supports Left/Right Ultrasonic sensors (HC-SR04) and Infrared (IR) distance/obstacle sensors.
Provides safety override signals for steering and emergency braking.
"""

import logging
import time
from typing import Tuple, Optional
from config import SensorConfig

try:
    import RPi.GPIO as GPIO
    RPI_GPIO_AVAILABLE = True
except (ImportError, RuntimeError):
    RPI_GPIO_AVAILABLE = False


class UltrasonicSensor:
    """Ultrasonic distance sensor (HC-SR04)."""

    def __init__(self, trig_pin: int, echo_pin: int):
        self.trig_pin = trig_pin
        self.echo_pin = echo_pin
        self.is_initialized = False

    def init_gpio(self):
        if RPI_GPIO_AVAILABLE:
            try:
                GPIO.setup(self.trig_pin, GPIO.OUT)
                GPIO.setup(self.echo_pin, GPIO.IN)
                GPIO.output(self.trig_pin, False)
                self.is_initialized = True
            except Exception as e:
                logging.error(f"Failed to initialize Ultrasonic GPIO (trig:{self.trig_pin}, echo:{self.echo_pin}): {e}")

    def measure_distance(self) -> float:
        """
        Measure distance in centimeters.
        Returns:
            distance (float): distance in cm (returns 999.0 on timeout/unavailable)
        """
        if not RPI_GPIO_AVAILABLE or not self.is_initialized:
            return 999.0

        try:
            # Send 10us trigger pulse
            GPIO.output(self.trig_pin, True)
            time.sleep(0.00001)
            GPIO.output(self.trig_pin, False)

            # Wait for echo high
            pulse_start = time.time()
            timeout = pulse_start + 0.04  # 40ms timeout (~6.8m max range)
            while GPIO.input(self.echo_pin) == 0:
                pulse_start = time.time()
                if pulse_start > timeout:
                    return 999.0

            # Wait for echo low
            pulse_end = time.time()
            while GPIO.input(self.echo_pin) == 1:
                pulse_end = time.time()
                if pulse_end > timeout:
                    return 999.0

            pulse_duration = pulse_end - pulse_start
            # Speed of sound: 34300 cm/s -> distance = (duration * 34300) / 2
            distance = round(pulse_duration * 17150, 2)
            return distance
        except Exception as e:
            logging.debug(f"Ultrasonic measurement error: {e}")
            return 999.0


class IRSensor:
    """Infrared digital obstacle/distance sensor (Active LOW / HIGH configurable)."""

    def __init__(self, pin: int, active_low: bool = True):
        self.pin = pin
        self.active_low = active_low
        self.is_initialized = False

    def init_gpio(self):
        if RPI_GPIO_AVAILABLE:
            try:
                GPIO.setup(self.pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
                self.is_initialized = True
            except Exception as e:
                logging.error(f"Failed to initialize IR GPIO {self.pin}: {e}")

    def is_obstacle_detected(self) -> bool:
        """Check if an obstacle is detected within threshold."""
        if not RPI_GPIO_AVAILABLE or not self.is_initialized:
            return False

        try:
            val = GPIO.input(self.pin)
            return (val == 0) if self.active_low else (val == 1)
        except Exception:
            return False


class SensorManager:
    """Manages all side and front distance sensors for reactive collision avoidance."""

    def __init__(self, config: SensorConfig):
        self.config = config
        self.left_sonar = UltrasonicSensor(config.left_trig_pin, config.left_echo_pin)
        self.right_sonar = UltrasonicSensor(config.right_trig_pin, config.right_echo_pin)
        self.left_ir = IRSensor(config.left_ir_pin)
        self.right_ir = IRSensor(config.right_ir_pin)

    def start(self):
        """Initialize all configured sensors."""
        if not self.config.enable_sensors:
            logging.info("External distance sensors are disabled in config.")
            return

        if RPI_GPIO_AVAILABLE:
            try:
                GPIO.setmode(GPIO.BCM)
                GPIO.setwarnings(False)
                self.left_sonar.init_gpio()
                self.right_sonar.init_gpio()
                self.left_ir.init_gpio()
                self.right_ir.init_gpio()
                logging.info("Sensor Manager started with GPIO.")
            except Exception as e:
                logging.error(f"Error initializing GPIO in SensorManager: {e}")
        else:
            logging.warning("RPi.GPIO not available. Sensors running in mock pass-through mode.")

    def get_obstacle_override(self, base_steering: float, base_throttle: float) -> Tuple[float, float, bool]:
        """
        Check side and front distances, adjust steering/throttle if a wall is too close.

        Returns:
            adjusted_steering (float): adjusted steering command
            adjusted_throttle (float): adjusted throttle command
            is_emergency (bool): True if obstacle requires immediate stop
        """
        if not self.config.enable_sensors:
            return base_steering, base_throttle, False

        left_dist = self.left_sonar.measure_distance()
        right_dist = self.right_sonar.measure_distance()
        left_ir_blocked = self.left_ir.is_obstacle_detected()
        right_ir_blocked = self.right_ir.is_obstacle_detected()

        adjusted_steering = base_steering
        adjusted_throttle = base_throttle
        is_emergency = False

        # Emergency stop condition
        if min(left_dist, right_dist) < self.config.emergency_stop_dist_cm:
            logging.warning("Emergency proximity threshold triggered!")
            return 0.0, 0.0, True

        # Left wall proximity push right
        if left_dist < self.config.side_warning_dist_cm or left_ir_blocked:
            bias = (self.config.side_warning_dist_cm - left_dist) / self.config.side_warning_dist_cm
            adjusted_steering = max(adjusted_steering, bias * 0.8)

        # Right wall proximity push left
        if right_dist < self.config.side_warning_dist_cm or right_ir_blocked:
            bias = (self.config.side_warning_dist_cm - right_dist) / self.config.side_warning_dist_cm
            adjusted_steering = min(adjusted_steering, -bias * 0.8)

        return adjusted_steering, adjusted_throttle, is_emergency

    def cleanup(self):
        """Clean up GPIO resources."""
        if RPI_GPIO_AVAILABLE and self.config.enable_sensors:
            try:
                GPIO.cleanup()
                logging.info("GPIO cleanup completed.")
            except Exception as e:
                logging.error(f"Error during GPIO cleanup: {e}")
