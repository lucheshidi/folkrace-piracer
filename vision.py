"""
Computer Vision module for Folkrace road and track sensing using OpenCV and NumPy.
Processes camera frames to calculate track center offset and steering guidance.
"""

import logging
from typing import Tuple, Optional
import numpy as np

try:
    import cv2
except ImportError:
    cv2 = None

from config import VisionConfig


class RoadPerception:
    """Perception pipeline for road condition sensing and lane/track following."""

    def __init__(self, config: VisionConfig):
        self.config = config

    def extract_roi(self, frame: np.ndarray) -> Tuple[np.ndarray, int, int]:
        """Crop frame to Region of Interest (ROI) containing the relevant track area."""
        h, w = frame.shape[:2]
        y_start = int(h * self.config.roi_top_ratio)
        y_end = int(h * self.config.roi_bottom_ratio)
        roi = frame[y_start:y_end, :]
        return roi, y_start, y_end

    def preprocess_frame(self, roi: np.ndarray) -> np.ndarray:
        """
        Preprocess ROI to extract track / line mask.
        Supports color thresholding and edge detection.
        """
        if cv2 is None:
            # Fallback if cv2 is not available
            return np.ones((roi.shape[0], roi.shape[1]), dtype=np.uint8) * 255

        # 1. Gaussian Blur to reduce noise
        blurred = cv2.GaussianBlur(roi, (5, 5), 0)

        # 2. Extract mask based on detection mode
        if self.config.detection_mode == "lane_line":
            # HSV threshold for bright lane lines (white/bright yellow)
            hsv = cv2.cvtColor(blurred, cv2.COLOR_BGR2HSV)
            mask = cv2.inRange(
                hsv,
                np.array(self.config.hsv_white_lower, dtype=np.uint8),
                np.array(self.config.hsv_white_upper, dtype=np.uint8),
            )
        elif self.config.detection_mode == "color_mask":
            # HSV threshold for dark track on lighter floor
            hsv = cv2.cvtColor(blurred, cv2.COLOR_BGR2HSV)
            mask = cv2.inRange(
                hsv,
                np.array(self.config.hsv_dark_lower, dtype=np.uint8),
                np.array(self.config.hsv_dark_upper, dtype=np.uint8),
            )
        else:
            # Default 'edge_contours' / adaptive: Gray + Otsu + Canny
            gray = cv2.cvtColor(blurred, cv2.COLOR_BGR2GRAY)
            # Thresholding to separate track from background
            _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            edges = cv2.Canny(thresh, self.config.canny_threshold1, self.config.canny_threshold2)
            # Morphological closing to bridge gaps
            kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
            mask = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel)

        return mask

    def process_frame(self, frame: np.ndarray) -> Tuple[float, bool, Optional[np.ndarray]]:
        """
        Process incoming frame and compute track offset error.

        Returns:
            error (float): Normalized track center offset from vehicle center [-1.0, 1.0].
                           Negative: steer left, Positive: steer right.
            detected (bool): Whether valid track was detected.
            debug_frame (np.ndarray): Annotated visualization image (or None if disabled).
        """
        if frame is None or frame.size == 0:
            return 0.0, False, None

        h, w = frame.shape[:2]
        center_x = w / 2.0
        roi, y_start, y_end = self.extract_roi(frame)
        roi_h, roi_w = roi.shape[:2]

        mask = self.preprocess_frame(roi)

        # Multi-slice horizontal scanning for robust centroid tracking
        num_slices = max(1, self.config.num_scan_slices)
        slice_height = roi_h // num_slices
        slice_centers = []
        slice_weights = []

        debug_frame = frame.copy() if self.config.show_debug_window and cv2 is not None else None

        for i in range(num_slices):
            slice_y1 = i * slice_height
            slice_y2 = (i + 1) * slice_height
            slice_mask = mask[slice_y1:slice_y2, :]

            # Find non-zero points or contour moments
            if cv2 is not None:
                moments = cv2.moments(slice_mask)
                if moments["m00"] > 50:  # Minimum pixel threshold
                    cx = moments["m10"] / moments["m00"]
                    # Slices closer to bottom (higher i) have higher weight for immediate steering
                    weight = 1.0 + (i / float(num_slices))
                    slice_centers.append(cx)
                    slice_weights.append(weight)

                    if debug_frame is not None:
                        # Draw center points in debug frame
                        abs_y = y_start + slice_y1 + (slice_height // 2)
                        cv2.circle(debug_frame, (int(cx), abs_y), 5, (0, 255, 0), -1)
                        cv2.line(debug_frame, (0, y_start + slice_y1), (w, y_start + slice_y1), (50, 50, 50), 1)

        if slice_centers:
            # Weighted average center
            target_x = float(np.average(slice_centers, weights=slice_weights))
            # Normalized error [-1.0, 1.0]
            error = (target_x - center_x) / center_x
            error = float(np.clip(error, -1.0, 1.0))
            detected = True

            if debug_frame is not None:
                # Draw vehicle center line & target steer line
                cv2.line(debug_frame, (int(center_x), h), (int(center_x), y_start), (255, 0, 0), 2)
                cv2.line(debug_frame, (int(center_x), h), (int(target_x), y_start + (roi_h // 2)), (0, 0, 255), 2)
                # Text overlay
                info_text = f"Err: {error:+.2f} | Detected: True"
                cv2.putText(debug_frame, info_text, (20, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
        else:
            # No valid track detected in ROI
            error = 0.0
            detected = False
            if debug_frame is not None:
                cv2.putText(debug_frame, "Track Lost! Searching...", (20, 30),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)

        if debug_frame is not None:
            # Draw ROI boundary
            cv2.rectangle(debug_frame, (0, y_start), (w, y_end), (255, 255, 0), 1)

        return error, detected, debug_frame
