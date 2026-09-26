"""Laptop webcam frames, leaving the Reachy camera free. Windows-compatible via OpenCV."""

from __future__ import annotations

import logging

import cv2
import numpy as np
from numpy.typing import NDArray


logger = logging.getLogger(__name__)


class LaptopCamera:
    """BGR frames from the webcam via OpenCV (Windows/Linux/macOS)."""

    def __init__(self) -> None:
        self.device_name: str | None = None
        self._cap: cv2.VideoCapture | None = None

    def open(self) -> None:
        cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
        if not cap.isOpened():
            # Fallback: try without DirectShow backend
            cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            raise RuntimeError(
                "No laptop camera found. Make sure a webcam is connected and not in use."
            )
        self._cap = cap
        self.device_name = "webcam (index 0)"
        logger.info("Laptop camera opened via OpenCV: %s", self.device_name)

    def read(self) -> NDArray[np.uint8] | None:
        """Return the newest BGR frame, or None if not available."""
        cap = self._cap
        if cap is None:
            return None
        ret, frame = cap.read()
        if not ret or frame is None:
            return None
        return frame

    def close(self) -> None:
        cap = self._cap
        self._cap = None
        if cap is not None:
            cap.release()
            logger.info("Laptop camera closed.")
