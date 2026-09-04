"""
Main entry point for PiRacer Pro Folkrace Autonomous Vehicle.
Integrates OpenCV vision, Picamera2 capture, PID motion control, and sensor avoidance.
"""

import argparse
import logging
import signal
import sys
import time

from config import AppConfig
from camera import Camera
from vision import RoadPerception
from controller import VehicleController
from sensors import SensorManager

try:
    import cv2
except ImportError:
    cv2 = None

# Global running state flag
running = True


def signal_handler(signum, frame):
    """Handle termination signals safely."""
    global running
    logging.info(f"Termination signal {signum} received. Stopping vehicle...")
    running = False


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Folkrace Autonomous Driving on PiRacer Pro")
    parser.add_argument("--display", action="store_true", help="Show live OpenCV visual debug window")
    parser.add_argument("--throttle", type=float, default=None, help="Override base throttle (e.g. 0.3)")
    parser.add_argument("--mode", type=str, choices=["edge_contours", "lane_line", "color_mask"],
                        default=None, help="Road perception detection mode")
    parser.add_argument("--enable-sensors", action="store_true", help="Enable ultrasonic/IR side sensors")
    parser.add_argument("--fps", type=int, default=30, help="Target loop frequency in Hz")
    return parser.parse_args()


def main():
    global running

    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S"
    )

    # Register system signals for graceful exit
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    args = parse_args()

    # Load configuration
    config = AppConfig()
    if args.display:
        config.vision.show_debug_window = True
    if args.throttle is not None:
        config.control.base_throttle = args.throttle
    if args.mode is not None:
        config.vision.detection_mode = args.mode
    if args.enable_sensors:
        config.sensor.enable_sensors = True
    if args.fps is not None:
        config.target_loop_hz = args.fps

    logging.info("=" * 50)
    logging.info(" Starting Folkrace PiRacer Pro Autonomous System")
    logging.info(f" Mode: {config.vision.detection_mode}")
    logging.info(f" Base Throttle: {config.control.base_throttle}")
    logging.info(f" Debug Window: {config.vision.show_debug_window}")
    logging.info(f" Sensors Enabled: {config.sensor.enable_sensors}")
    logging.info("=" * 50)

    # Initialize subsystems
    camera = Camera(
        width=config.camera.width,
        height=config.camera.height,
        framerate=config.camera.framerate,
        format=config.camera.format
    )
    perception = RoadPerception(config.vision)
    vehicle = VehicleController(config.control)
    sensors = SensorManager(config.sensor)

    try:
        camera.start()
        vehicle.start()
        sensors.start()
        logging.info("All subsystems initialized. Starting main control loop...")

        loop_period = 1.0 / config.target_loop_hz
        frame_count = 0
        fps_start_time = time.time()
        current_fps = 0.0

        while running:
            loop_start = time.time()

            # 1. Capture camera frame
            frame = camera.capture_frame()

            # 2. Vision perception: process road condition & calculate steering offset
            error, detected, debug_frame = perception.process_frame(frame)

            # 3. Motion control calculation (PID + dynamic speed scaling)
            steering, throttle = vehicle.compute_control(error, detected)

            # 4. Sensor override (side proximity & obstacle avoidance)
            steering, throttle, is_emergency = sensors.get_obstacle_override(steering, throttle)

            # 5. Apply actuator commands
            if is_emergency:
                vehicle.stop()
            else:
                vehicle.set_drive(steering, throttle)

            # 6. Debug display
            if config.vision.show_debug_window and debug_frame is not None and cv2 is not None:
                # Add telemetry info to debug frame
                telemetry = f"FPS: {current_fps:.1f} | Steer: {steering:+.2f} | Thr: {throttle:.2f}"
                cv2.putText(debug_frame, telemetry, (20, debug_frame.shape[0] - 20),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
                cv2.imshow("PiRacer Folkrace Vision", debug_frame)
                key = cv2.waitKey(1) & 0xFF
                if key == ord('q') or key == 27:  # 'q' or ESC
                    logging.info("Exit requested via GUI key press.")
                    break

            # FPS calculation
            frame_count += 1
            elapsed_fps = time.time() - fps_start_time
            if elapsed_fps >= 1.0:
                current_fps = frame_count / elapsed_fps
                frame_count = 0
                fps_start_time = time.time()
                logging.info(f"Running @ {current_fps:.1f} FPS | Steer: {steering:+.2f} | Throttle: {throttle:.2f}")

            # Sleep to maintain target loop frequency
            process_duration = time.time() - loop_start
            sleep_time = loop_period - process_duration
            if sleep_time > 0:
                time.sleep(sleep_time)

    except KeyboardInterrupt:
        logging.info("KeyboardInterrupt received.")
    except Exception as e:
        logging.error(f"Unexpected error in main loop: {e}", exc_info=True)
    finally:
        logging.info("Cleaning up and stopping vehicle...")
        vehicle.stop()
        camera.stop()
        sensors.cleanup()
        if cv2 is not None:
            cv2.destroyAllWindows()
        logging.info("System terminated safely.")


if __name__ == "__main__":
    main()
