from __future__ import annotations

import math
import threading
from collections.abc import Sequence
from typing import Protocol

import cv2
import numpy as np
from rapidocr_onnxruntime import RapidOCR

from labelcheck.models import TextBlock


class OcrError(RuntimeError):
    """Separate engine failure from a successful inference that found no text."""


class _Backend(Protocol):
    def __call__(self, image: np.ndarray) -> object: ...


class OcrEngine:
    """Contain the engine-specific API and serialize its mutable inference state."""

    def __init__(self, backend: _Backend | None = None) -> None:
        self._backend: _Backend = backend if backend is not None else RapidOCR()
        self._inference_lock = threading.Lock()

    def recognize(self, image: np.ndarray) -> list[TextBlock]:
        """Preserve valid OCR text and geometry while ignoring malformed engine rows."""

        if (
            not isinstance(image, np.ndarray)
            or image.dtype != np.uint8
            or image.ndim != 3
            or image.shape[2] != 3
            or image.size == 0
        ):
            raise ValueError("OCR input must be a non-empty uint8 BGR image")

        try:
            with self._inference_lock:
                output = self._backend(np.ascontiguousarray(image))
        except Exception as error:
            raise OcrError("OCR inference failed") from error

        return _parse_output(output)


def _parse_output(output: object) -> list[TextBlock]:
    if not isinstance(output, Sequence) or isinstance(output, (str, bytes)) or not output:
        return []
    rows = output[0]
    if rows is None or not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        return []

    blocks: list[TextBlock] = []
    for row in rows:
        if not isinstance(row, Sequence) or isinstance(row, (str, bytes)) or len(row) < 3:
            continue
        text = row[1]
        if not isinstance(text, str) or not text.strip():
            continue
        try:
            points = np.asarray(row[0], dtype=np.float64)
            confidence = float(row[2])
        except (TypeError, ValueError, OverflowError):
            continue
        if points.shape != (4, 2) or not np.isfinite(points).all():
            continue
        if not math.isfinite(confidence) or not 0.0 <= confidence <= 1.0:
            continue
        bbox = tuple((float(x), float(y)) for x, y in points)
        blocks.append(TextBlock(text=text, bbox=bbox, confidence=confidence))
    return blocks


_ENGINE: OcrEngine | None = None
_ENGINE_LOCK = threading.Lock()
_WARMED = False
_WARM_LOCK = threading.Lock()


def get_engine() -> OcrEngine:
    """Load exactly one offline OCR engine even under concurrent first requests."""

    global _ENGINE
    if _ENGINE is None:
        with _ENGINE_LOCK:
            if _ENGINE is None:
                _ENGINE = OcrEngine()
    return _ENGINE


def recognize(image: np.ndarray) -> list[TextBlock]:
    """Route inference through the process singleton without exposing RapidOCR."""

    return get_engine().recognize(image)


def warm() -> OcrEngine:
    """Exercise the full local model once so the first label does not pay startup cost."""

    global _WARMED
    engine = get_engine()
    if not _WARMED:
        with _WARM_LOCK:
            if not _WARMED:
                image = np.full((32, 128, 3), 255, dtype=np.uint8)
                cv2.putText(
                    image,
                    "WARM",
                    (3, 25),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.65,
                    (0, 0, 0),
                    1,
                    cv2.LINE_AA,
                )
                engine.recognize(image)
                _WARMED = True
    return engine
