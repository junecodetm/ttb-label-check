"""Benchmark warm OCR latency and semantic field accuracy on every synthetic variant."""

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

from fixture_factory import sample_application_record  # noqa: E402

from labelcheck import ocr, pipeline  # noqa: E402
from labelcheck.extract import FieldCandidate  # noqa: E402
from labelcheck.models import (  # noqa: E402
    ApplicationRecord,
    LabelReport,
    Status,
    TextBlock,
)

BENCH_DIRECTORY = PROJECT_ROOT / ".bench_images"
VARIANT_FILENAMES = (
    "clean.png",
    "ornate.png",
    "rotated.png",
    "glare.png",
    "low_resolution.png",
    "combined_adversarial.png",
)
RUNS_PER_VARIANT = 3
ACCURACY_FIELDS = (
    ("brand_name", "brand"),
    ("class_type", "class"),
    ("alcohol_content", "alcohol"),
    ("net_contents", "net"),
    ("bottler", "bottler"),
    ("government_warning", "warning"),
)


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
    total_seconds: float

    @property
    def extraction_rules_seconds(self) -> float:
        return self.extraction_seconds + self.rules_orchestration_seconds


def _linear_percentile(samples: Sequence[float], quantile: float) -> float:
    """Use R-7 interpolation so repeated benchmark runs remain comparable."""

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


def _field_accuracy(report: LabelReport) -> dict[str, bool]:
    """Count only the six visible semantic fields, excluding duplicate/heuristic checks."""

    return {
        field_name: report.results[field_name].status is Status.PASS
        for field_name, _label in ACCURACY_FIELDS
    }


def _field_correct_counts(samples: Sequence[dict[str, bool]]) -> dict[str, int]:
    """Expose intermittent reads instead of collapsing repeated samples into one verdict."""

    if not samples:
        return {}
    return {
        field_name: sum(sample.get(field_name, False) for sample in samples)
        for field_name in samples[0]
    }


def _measure_run(
    image_bytes: bytes,
    expected: ApplicationRecord,
) -> tuple[LabelReport, _RunTiming]:
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

    def timed_extract(
        blocks: Sequence[TextBlock],
        image: np.ndarray,
    ) -> dict[str, FieldCandidate]:
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
        report = pipeline.verify(image_bytes, expected)
        total_seconds = perf_counter() - started

    rules_orchestration_seconds = total_seconds - (
        stages.decode_preprocess_seconds + stages.ocr_seconds + stages.extraction_seconds
    )
    return report, _RunTiming(
        decode_preprocess_seconds=stages.decode_preprocess_seconds,
        ocr_seconds=stages.ocr_seconds,
        extraction_seconds=stages.extraction_seconds,
        rules_orchestration_seconds=rules_orchestration_seconds,
        total_seconds=total_seconds,
    )


def main() -> None:
    """Warm once, then report tail latency and field correctness without hiding either."""

    missing = [name for name in VARIANT_FILENAMES if not (BENCH_DIRECTORY / name).is_file()]
    if missing:
        names = ", ".join(missing)
        raise SystemExit(
            f"Missing benchmark images: {names}. Run tools/make_bench_images.py first."
        )

    expected = sample_application_record()
    ocr.warm()

    timings_by_variant: dict[str, list[_RunTiming]] = {}
    accuracy_by_variant: dict[str, list[dict[str, bool]]] = {}
    for filename in VARIANT_FILENAMES:
        image_bytes = (BENCH_DIRECTORY / filename).read_bytes()
        variant = Path(filename).stem
        timings_by_variant[variant] = []
        accuracy_by_variant[variant] = []
        for _sample_number in range(RUNS_PER_VARIANT):
            report, timing = _measure_run(image_bytes, expected)
            timings_by_variant[variant].append(timing)
            accuracy_by_variant[variant].append(_field_accuracy(report))

    all_timings = [
        timing for variant_timings in timings_by_variant.values() for timing in variant_timings
    ]
    stage_samples = (
        (
            "decode + preprocess",
            [timing.decode_preprocess_seconds for timing in all_timings],
        ),
        ("OCR", [timing.ocr_seconds for timing in all_timings]),
        (
            "extraction + rules",
            [timing.extraction_rules_seconds for timing in all_timings],
        ),
        ("end to end", [timing.total_seconds for timing in all_timings]),
    )

    print(
        f"Warm RapidOCR benchmark: {len(all_timings)} timed samples "
        f"({RUNS_PER_VARIANT} x {len(VARIANT_FILENAMES)}); model warm-up excluded"
    )
    print("\nTIMING (seconds, all variants)")
    print(f"{'stage':<24} {'p50':>8} {'p95':>8}")
    for label, samples in stage_samples:
        print(
            f"{label:<24} {_linear_percentile(samples, 0.50):>8.3f} "
            f"{_linear_percentile(samples, 0.95):>8.3f}"
        )

    print("\nEND TO END BY VARIANT (seconds)")
    print(f"{'variant':<23} {'p50':>8} {'p95':>8}")
    for variant, timings in timings_by_variant.items():
        samples = [timing.total_seconds for timing in timings]
        print(
            f"{variant:<23} {_linear_percentile(samples, 0.50):>8.3f} "
            f"{_linear_percentile(samples, 0.95):>8.3f}"
        )

    print(f"\nFIELD ACCURACY BY VARIANT (correct timed runs / {RUNS_PER_VARIANT})")
    labels = " ".join(f"{label:>7}" for _field_name, label in ACCURACY_FIELDS)
    print(f"{'variant':<23} {labels} {'total':>7}")
    for variant, samples in accuracy_by_variant.items():
        correct_counts = _field_correct_counts(samples)
        marks = " ".join(
            f"{f'{correct_counts[field_name]}/{len(samples)}':>7}"
            for field_name, _label in ACCURACY_FIELDS
        )
        correct = sum(correct_counts.values())
        possible = len(ACCURACY_FIELDS) * len(samples)
        print(f"{variant:<23} {marks} {f'{correct}/{possible}':>7}")


if __name__ == "__main__":
    main()
