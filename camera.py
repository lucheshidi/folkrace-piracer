"""
Camera abstraction module supporting Picamera2 for Raspberry Pi 4/5
and fallback to OpenCV VideoCapture or synthetic frames for local testing.
"""

import logging
import time
import numpy as np

try:
    from picamera2 import Picamera2
    PICAMERA2_AVAILABLE = True
except ImportError:
    PICAMERA2_AVAILABLE = False

try:
    import cv2
except ImportError:
    cv2 = None


class Camera:
    """Wrapper around Picamera2 with fallback support."""

    def __init__(self, width: int = 640, height: int = 360, framerate: int = 30, format: str = "RGB888"):
        self.width = width
        self.height = height
        self.framerate = framerate
        self.format = format
        self.picam2 = None
        self.cap = None
        self.is_running = False

    def start(self):
        """Initialize and start the camera stream."""
        if PICAMERA2_AVAILABLE:
            logging.info("Initializing Picamera2 (OV5647 compatible)...")
            try:
                self.picam2 = Picamera2()
                # Try preview configuration with native sensor resolution
                try:
                    cam_config = self.picam2.create_video_configuration(
                        main={"size": (self.width, self.height), "format": self.format}
                    )
                except Exception:
                    cam_config = self.picam2.create_preview_configuration(
                        main={"size": (self.width, self.height), "format": self.format}
                    )
                self.picam2.configure(cam_config)
                self.picam2.start()
                # Warm up
                time.sleep(1.0)
                self.is_running = True
                logging.info(f"Picamera2 started successfully ({self.width}x{self.height} @ {self.framerate}fps)")
                return
            except Exception as e:
                logging.warning(f"Picamera2 failed to start ({e}). Trying VideoCapture fallback...")
                if self.picam2 is not None:
                    try:
                        self.picam2.close()
                    except Exception:
                        pass
                    self.picam2 = None

        if cv2 is not None:
            logging.warning("Trying OpenCV VideoCapture fallback (index 0)...")
            try:
                self.cap = cv2.VideoCapture(0)
                if self.cap.isOpened():
                    self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
                    self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
                    self.cap.set(cv2.CAP_PROP_FPS, self.framerate)
                    self.is_running = True
                    logging.info("OpenCV VideoCapture fallback started.")
                    return
            except Exception as e:
                logging.warning(f"OpenCV VideoCapture failed: {e}")

        logging.warning("No physical camera could be opened. Running in synthetic mock frame mode.")
        self.is_running = True

    def capture_frame(self) -> np.ndarray:
        """
        Capture a single frame as a NumPy array (BGR format for OpenCV processing).
        Returns:
            np.ndarray: BGR image frame (H, W, 3)
        """
        if not self.is_running:
            raise RuntimeError("Camera is not started. Call camera.start() first.")

        if PICAMERA2_AVAILABLE and self.picam2 is not None:
            # Picamera2 capture_array returns RGB or BGR based on configuration
            frame = self.picam2.capture_array()
            if self.format == "RGB888" and cv2 is not None:
                # Convert RGB to BGR for standard OpenCV processing
                return cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
            return frame

        elif self.cap is not None and self.cap.isOpened():
            ret, frame = self.cap.read()
            if ret and frame is not None:
                if (frame.shape[1], frame.shape[0]) != (self.width, self.height):
                    frame = cv2.resize(frame, (self.width, self.height))
                return frame

        # Fallback synthetic frame with simulated road for testing without hardware
        synthetic_frame = np.zeros((self.height, self.width, 3), dtype=np.uint8)
        # Draw mock road (gray trapezoid) and white line in the middle
        if cv2 is not None:
            pts = np.array([
                [self.width * 0.2, self.height],
                [self.width * 0.4, self.height * 0.4],
                [self.width * 0.6, self.height * 0.4],
                [self.width * 0.8, self.height]
            ], np.int32)
            cv2.fillPoly(synthetic_frame, [pts], (80, 80, 80))
            cv2.line(synthetic_frame, (int(self.width * 0.5), int(self.height * 0.4)),
                     (int(self.width * 0.5), self.height), (255, 255, 255), 4)
        return synthetic_frame

    def stop(self):
        """Stop and release camera resources."""
        if self.picam2 is not None:
            try:
                self.picam2.stop()
                self.picam2.close()
            except Exception as e:
                logging.error(f"Error stopping Picamera2: {e}")
            self.picam2 = None

        if self.cap is not None:
            try:
                self.cap.release()
            except Exception as e:
                logging.error(f"Error releasing VideoCapture: {e}")
            self.cap = None

        self.is_running = False
        logging.info("Camera stopped.")
