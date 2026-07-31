"""Measure warm single-label verification with interpolated tail latency."""

from __future__ import annotations

import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from unittest.mock import patch

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "tests"))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from fixture_factory import make_label, sample_application_record  # noqa: E402

from labelcheck import ocr, pipeline  # noqa: E402
from labelcheck.extract import FieldCandidate  # noqa: E402
from labelcheck.models import ApplicationRecord, TextBlock  # noqa: E402

RUN_COUNT = 20


@dataclass(slots=True)
class _StageAccumulator:
    decode_preprocess_seconds: float = 0.0
    ocr_seconds: float = 0.0
    extraction_seconds: float = 0.0


@dataclass(frozen=True, slots=True)
class _RunTiming:
    decode_preprocess_seconds: float
    ocr_seconds: float
    extraction_seconds: float
    rules_orchestration_seconds: float
    total_wall_seconds: float

    @property
    def extraction_rules_seconds(self) -> float:
        return self.extraction_seconds + self.rules_orchestration_seconds


def _measure_run(image_bytes: bytes, expected: ApplicationRecord) -> _RunTiming:
    stages = _StageAccumulator()
    preprocess_image = pipeline.preprocess.preprocess_image
    recognize = pipeline.ocr.recognize
    extract_candidates = pipeline.extract_candidates

    def timed_preprocess(source: bytes) -> np.ndarray:
        started = perf_counter()
        try:
            return preprocess_image(source)
        finally:
            stages.decode_preprocess_seconds += perf_counter() - started

    def timed_recognize(image: np.ndarray) -> list[TextBlock]:
        started = perf_counter()
        try:
            return recognize(image)
        finally:
            stages.ocr_seconds += perf_counter() - started

    def timed_extract(blocks: Sequence[TextBlock], image: np.ndarray) -> dict[str, FieldCandidate]:
        started = perf_counter()
        try:
            return extract_candidates(blocks, image)
        finally:
            stages.extraction_seconds += perf_counter() - started

    with (
        patch.object(pipeline.preprocess, "preprocess_image", new=timed_preprocess),
        patch.object(pipeline.ocr, "recognize", new=timed_recognize),
        patch.object(pipeline, "extract_candidates", new=timed_extract),
    ):
        started = perf_counter()
        pipeline.verify(image_bytes, expected)
        total_wall_seconds = perf_counter() - started

    rules_orchestration_seconds = total_wall_seconds - (
        stages.decode_preprocess_seconds + stages.ocr_seconds + stages.extraction_seconds
    )
    return _RunTiming(
        decode_preprocess_seconds=stages.decode_preprocess_seconds,
        ocr_seconds=stages.ocr_seconds,
        extraction_seconds=stages.extraction_seconds,
        rules_orchestration_seconds=rules_orchestration_seconds,
        total_wall_seconds=total_wall_seconds,
    )


def _linear_percentile(samples: Sequence[float], quantile: float) -> float:
    """Use R-7 interpolation so percentile calculations stay reproducible."""

    if not samples:
        raise ValueError("at least one timing sample is required")
    if not 0.0 <= quantile <= 1.0:
        raise ValueError("quantile must be between zero and one")

    ordered = sorted(samples)
    rank = (len(ordered) - 1) * quantile
    lower_index = int(rank)
    upper_index = min(lower_index + 1, len(ordered) - 1)
    fraction = rank - lower_index
    return ordered[lower_index] + fraction * (ordered[upper_index] - ordered[lower_index])


def main() -> None:
    """Exclude model startup so the measurements match the documented warm budget."""

    image_bytes = make_label()
    expected = sample_application_record()
    ocr.warm()

    timings: list[_RunTiming] = []
    for run_number in range(1, RUN_COUNT + 1):
        timing = _measure_run(image_bytes, expected)
        timings.append(timing)
        print(
            f"run {run_number}: "
            f"decode + preprocess = {timing.decode_preprocess_seconds:.3f}s | "
            f"OCR = {timing.ocr_seconds:.3f}s | "
            "extraction + rules/orchestration = "
            f"{timing.extraction_rules_seconds:.3f}s | "
            f"total wall clock = {timing.total_wall_seconds:.3f}s"
        )

    wall_samples = [timing.total_wall_seconds for timing in timings]
    p50 = _linear_percentile(wall_samples, 0.50)
    p95 = _linear_percentile(wall_samples, 0.95)
    print(
        f"WALL-CLOCK SUMMARY: p50 = {p50:.3f}s | p95 = {p95:.3f}s "
        f"(n = {RUN_COUNT}, R-7 linear interpolation at rank (n - 1) * q)"
    )


if __name__ == "__main__":
    main()
