"""
Hardware Diagnostic and Test Script for Waveshare PiRacer Pro.
Runs isolated tests on Steering Servo, Motor ESC, and Camera.
Usage:
    python3 test_hardware.py
"""

import sys
import time
import logging

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(levelname)s] %(message)s")


def test_i2c():
    logging.info("--- [1/3] Testing I2C and PCA9685 connection ---")
    try:
        import smbus2
        bus = smbus2.SMBus(1)
        # Try reading PCA9685 MODE1 register at 0x40
        mode1 = bus.read_byte_data(0x40, 0x00)
        logging.info(f"✅ I2C device 0x40 (PCA9685) detected! MODE1: {hex(mode1)}")
        bus.close()
        return True
    except Exception as e:
        logging.warning(f"I2C direct probe skipped/failed: {e}")
        return False


def test_steering_and_throttle():
    logging.info("--- [2/3] Testing Steering Servo & Motor ESC ---")
    driver = None
    driver_type = None

    # Try piracer-py
    try:
        from piracer.vehicles import PiRacerPro
        driver = PiRacerPro()
        driver_type = "piracer-py (PiRacerPro)"
        logging.info(f"✅ Successfully loaded {driver_type}")
    except Exception as e:
        logging.warning(f"piracer-py not available: {e}")

    # Try Adafruit ServoKit
    if driver is None:
        try:
            from adafruit_servokit import ServoKit
            driver = ServoKit(channels=16)
            driver.servo[0].set_pulse_width_range(1000, 2000)
            driver.continuous_servo[1].set_pulse_width_range(1000, 2000)
            driver_type = "adafruit-servokit (PCA9685)"
            logging.info(f"✅ Successfully loaded {driver_type}")
        except Exception as e:
            logging.warning(f"ServoKit not available: {e}")

    if driver is None:
        logging.error("❌ No hardware driver could be initialized! Please check I2C / piracer-py installation.")
        return False

    def set_drive(steer, thr):
        if driver_type.startswith("piracer-py"):
            driver.set_steering_percent(steer)
            driver.set_throttle_percent(thr)
        else:
            driver.servo[0].angle = (steer + 1.0) * 90.0
            driver.continuous_servo[1].throttle = thr

    try:
        # 1. ESC Neutral Arming
        logging.info("Arming ESC at neutral for 2 seconds (Listen for ESC beeps)...")
        set_drive(0.0, 0.0)
        time.sleep(2.0)

        # 2. Steering Servo Sweep
        logging.info("Testing Steering: Neutral (0.0)")
        set_drive(0.0, 0.0)
        time.sleep(1.0)

        logging.info("Testing Steering: Turn LEFT (-0.8)")
        set_drive(-0.8, 0.0)
        time.sleep(1.0)

        logging.info("Testing Steering: Neutral (0.0)")
        set_drive(0.0, 0.0)
        time.sleep(0.5)

        logging.info("Testing Steering: Turn RIGHT (+0.8)")
        set_drive(0.8, 0.0)
        time.sleep(1.0)

        logging.info("Testing Steering: Return to Neutral (0.0)")
        set_drive(0.0, 0.0)
        time.sleep(1.0)
        logging.info("✅ Steering servo test completed.")

        # 3. Motor Throttle Test (Ensure wheels are off the ground or hold the car!)
        logging.info("⚠️  ATTENTION: Motor throttle test about to begin in 2 seconds.")
        logging.info("   Please lift vehicle wheels off the ground to prevent runaway!")
        time.sleep(2.0)

        logging.info("Testing Motor: FORWARD (0.28) for 1.5 seconds...")
        set_drive(0.0, 0.28)
        time.sleep(1.5)

        logging.info("Testing Motor: BRAKE / STOP (0.0)...")
        set_drive(0.0, 0.0)
        time.sleep(1.0)

        logging.info("Testing Motor: REVERSE (-0.25) for 1.0 second...")
        set_drive(0.0, -0.25)
        time.sleep(1.0)

        logging.info("Testing Motor: FINAL STOP (0.0)")
        set_drive(0.0, 0.0)
        logging.info("✅ Motor ESC test completed successfully.")
        return True

    except Exception as e:
        logging.error(f"Error during actuator test: {e}")
        try:
            set_drive(0.0, 0.0)
        except Exception:
            pass
        return False


def test_camera():
    logging.info("--- [3/3] Testing Camera Capture ---")
    try:
        from camera import Camera
        cam = Camera(width=640, height=480)
        cam.start()
        frame = cam.capture_frame()
        cam.stop()
        if frame is not None:
            logging.info(f"✅ Camera capture OK! Frame shape: {frame.shape}")
            return True
        else:
            logging.error("❌ Captured frame is None!")
            return False
    except Exception as e:
        logging.error(f"❌ Camera test failed: {e}")
        return False


def main():
    logging.info("==================================================")
    logging.info(" Waveshare PiRacer Pro Hardware Self-Test Suite   ")
    logging.info("==================================================")

    test_i2c()
    actuator_ok = test_steering_and_throttle()
    cam_ok = test_camera()

    logging.info("==================================================")
    if actuator_ok and cam_ok:
        logging.info("🎉 ALL TESTS PASSED! Vehicle is ready for autonomous racing.")
    else:
        logging.warning("⚠️  Some tests reported issues. Please check wiring, battery power, and ESC switch.")
    logging.info("==================================================")


if __name__ == "__main__":
    main()
