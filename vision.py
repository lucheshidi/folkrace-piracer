"""
Computer Vision module for Folkrace road and track sensing using OpenCV and NumPy.
Processes camera frames to calculate track center offset and steering guidance.
Supports dual-edge boundary tracking, lane line centroid scanning, and adaptive thresholding.
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
        self.estimated_half_track_width = 150.0  # Default pixel width estimate for single-boundary fallback

    def extract_roi(self, frame: np.ndarray) -> Tuple[np.ndarray, int, int]:
        """Crop frame to Region of Interest (ROI) containing the relevant track area."""
        h, w = frame.shape[:2]
        y_start = int(h * self.config.roi_top_ratio)
        y_end = int(h * self.config.roi_bottom_ratio)
        roi = frame[y_start:y_end, :]
        return roi, y_start, y_end

    def preprocess_frame(self, roi: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """
        Preprocess ROI to extract track masks and edge maps.
        Returns:
            binary_mask (np.ndarray): Binary representation of lines/track.
            edge_map (np.ndarray): Canny edge map for boundary detection.
        """
        if cv2 is None:
            mask = np.ones((roi.shape[0], roi.shape[1]), dtype=np.uint8) * 255
            return mask, mask

        # 1. Gaussian Blur to reduce noise and camera sensor grain
        blurred = cv2.GaussianBlur(roi, (5, 5), 0)
        gray = cv2.cvtColor(blurred, cv2.COLOR_BGR2GRAY)

        # 2. Extract edge map using Canny
        edges = cv2.Canny(gray, self.config.canny_threshold1, self.config.canny_threshold2)

        # 3. Extract mask based on detection mode
        if self.config.detection_mode == "lane_line":
            # Detect bright/white or yellow guide line
            hsv = cv2.cvtColor(blurred, cv2.COLOR_BGR2HSV)
            mask_white = cv2.inRange(
                hsv,
                np.array(self.config.hsv_white_lower, dtype=np.uint8),
                np.array(self.config.hsv_white_upper, dtype=np.uint8),
            )
            # Grayscale high-intensity threshold fallback for bright lines
            _, mask_gray = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY)
            mask = cv2.bitwise_or(mask_white, mask_gray)

        elif self.config.detection_mode == "color_mask":
            # HSV threshold for dark track on lighter floor
            hsv = cv2.cvtColor(blurred, cv2.COLOR_BGR2HSV)
            mask = cv2.inRange(
                hsv,
                np.array(self.config.hsv_dark_lower, dtype=np.uint8),
                np.array(self.config.hsv_dark_upper, dtype=np.uint8),
            )

        else:
            # 'edge_contours' mode: Adaptive thresholding + edge morphological combination
            # Handles non-uniform indoor lighting much better than global Otsu
            adaptive = cv2.adaptiveThreshold(
                gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY_INV, 15, 3
            )
            kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
            mask = cv2.morphologyEx(adaptive, cv2.MORPH_CLOSE, kernel)

        return mask, edges

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

        mask, edges = self.preprocess_frame(roi)

        num_slices = max(1, self.config.num_scan_slices)
        slice_height = roi_h // num_slices
        slice_centers = []
        slice_weights = []

        debug_frame = frame.copy() if self.config.show_debug_window and cv2 is not None else None

        # Mode A: Dual-boundary edge corridor tracking for 'edge_contours'
        if self.config.detection_mode == "edge_contours" and cv2 is not None:
            for i in range(num_slices):
                slice_y1 = i * slice_height
                slice_y2 = (i + 1) * slice_height
                slice_edges = edges[slice_y1:slice_y2, :]

                # Find all non-zero edge pixel coordinates
                edge_points = np.where(slice_edges > 0)
                if len(edge_points[1]) > 10:
                    xs = edge_points[1]
                    left_boundary = np.min(xs)
                    right_boundary = np.max(xs)

                    # If left and right boundaries are separated by a plausible road width
                    if (right_boundary - left_boundary) > (roi_w * 0.2):
                        cx = (left_boundary + right_boundary) / 2.0
                        self.estimated_half_track_width = (right_boundary - left_boundary) / 2.0
                    elif left_boundary > center_x:
                        # Only right wall visible -> aim to the left of it
                        cx = max(0.0, left_boundary - self.estimated_half_track_width)
                    else:
                        # Only left wall visible -> aim to the right of it
                        cx = min(float(roi_w), right_boundary + self.estimated_half_track_width)

                    weight = 1.0 + (i / float(num_slices))
                    slice_centers.append(cx)
                    slice_weights.append(weight)

                    if debug_frame is not None:
                        abs_y = y_start + slice_y1 + (slice_height // 2)
                        cv2.circle(debug_frame, (int(cx), abs_y), 5, (0, 255, 0), -1)
                        cv2.circle(debug_frame, (int(left_boundary), abs_y), 4, (0, 0, 255), -1)
                        cv2.circle(debug_frame, (int(right_boundary), abs_y), 4, (255, 0, 0), -1)

        # Mode B: Centroid / Lane Line Moment Scanning
        if not slice_centers and cv2 is not None:
            for i in range(num_slices):
                slice_y1 = i * slice_height
                slice_y2 = (i + 1) * slice_height
                slice_mask = mask[slice_y1:slice_y2, :]

                moments = cv2.moments(slice_mask)
                if moments["m00"] > 50:
                    cx = moments["m10"] / moments["m00"]
                    weight = 1.0 + (i / float(num_slices))
                    slice_centers.append(cx)
                    slice_weights.append(weight)

                    if debug_frame is not None:
                        abs_y = y_start + slice_y1 + (slice_height // 2)
                        cv2.circle(debug_frame, (int(cx), abs_y), 5, (0, 255, 0), -1)

        # Final guidance error calculation
        if slice_centers:
            target_x = float(np.average(slice_centers, weights=slice_weights))
            # Normalized error [-1.0, 1.0]: target offset from image center
            error = (target_x - center_x) / center_x
            error = float(np.clip(error, -1.0, 1.0))
            detected = True

            if debug_frame is not None:
                # Target path lines
                cv2.line(debug_frame, (int(center_x), h), (int(center_x), y_start), (255, 0, 0), 2)
                cv2.line(debug_frame, (int(center_x), h), (int(target_x), y_start + (roi_h // 2)), (0, 0, 255), 2)
                cv2.putText(debug_frame, f"Err: {error:+.2f} | Mode: {self.config.detection_mode}",
                            (20, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
        else:
            error = 0.0
            detected = False
            if debug_frame is not None:
                cv2.putText(debug_frame, "Track Lost! Searching...", (20, 30),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)

        if debug_frame is not None:
            cv2.rectangle(debug_frame, (0, y_start), (w, y_end), (255, 255, 0), 1)

        return error, detected, debug_frame
