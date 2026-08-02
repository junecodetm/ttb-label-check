from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

import numpy as np
import pytest

from labelcheck.extract import FieldCandidate
from labelcheck.models import FieldResult, LabelReport, Status, TextBlock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import bench_ocr  # noqa: E402


def _result(status: Status) -> FieldResult:
    return FieldResult(status, "expected", "extracted", 100.0, b"crop", "detail")


def test_percentile_uses_r7_linear_interpolation() -> None:
    assert bench_ocr._linear_percentile([1.0, 2.0, 3.0, 4.0], 0.50) == pytest.approx(2.5)
    assert bench_ocr._linear_percentile([1.0, 2.0, 3.0, 4.0], 0.95) == pytest.approx(3.85)


def test_accuracy_counts_six_semantic_label_fields() -> None:
    report = LabelReport(
        {
            "brand_name": _result(Status.PASS),
            "class_type": _result(Status.PASS),
            "alcohol_content": _result(Status.FAIL),
            "net_contents": _result(Status.PASS),
            "net_contents_standard_of_fill": _result(Status.PASS),
            "bottler": _result(Status.PASS),
            "government_warning": _result(Status.PASS),
            "origin_country": _result(Status.NOT_EVALUATED),
            "government_warning_prefix": _result(Status.PASS),
            "government_warning_bold": _result(Status.NOT_EVALUATED),
            "government_warning_type_size": _result(Status.NOT_EVALUATED),
        }
    )

    accuracy = bench_ocr._field_accuracy(report)

    assert accuracy == {
        "brand_name": True,
        "class_type": True,
        "alcohol_content": False,
        "net_contents": True,
        "bottler": True,
        "government_warning": True,
    }


def test_accuracy_counts_preserve_intermittent_results() -> None:
    samples = [
        {"brand_name": True, "class_type": True},
        {"brand_name": False, "class_type": True},
        {"brand_name": True, "class_type": True},
    ]

    assert bench_ocr._field_correct_counts(samples) == {
        "brand_name": 2,
        "class_type": 3,
    }


def test_measure_run_attributes_rules_to_extraction_stage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image = np.zeros((2, 3, 3), dtype=np.uint8)
    block = TextBlock("text", ((0.0, 0.0),) * 4, 0.9)
    candidate = FieldCandidate("text", (), (), 0.9, b"crop", "FOUND")
    report = LabelReport({"brand_name": _result(Status.PASS)})

    monkeypatch.setattr(bench_ocr.pipeline.preprocess, "preprocess_image", lambda _data: image)
    monkeypatch.setattr(bench_ocr.pipeline.ocr, "recognize", lambda _image: [block])
    monkeypatch.setattr(
        bench_ocr.pipeline,
        "extract_candidates",
        lambda _blocks, _image: {"brand_name": candidate},
    )

    def fake_verify(_data: bytes, _expected: object) -> LabelReport:
        processed = bench_ocr.pipeline.preprocess.preprocess_image(b"image")
        blocks: Sequence[TextBlock] = bench_ocr.pipeline.ocr.recognize(processed)
        bench_ocr.pipeline.extract_candidates(blocks, processed)
        return report

    monkeypatch.setattr(bench_ocr.pipeline, "verify", fake_verify)
    clock = iter((0.0, 1.0, 3.0, 3.0, 7.0, 7.0, 8.0, 10.0))
    monkeypatch.setattr(bench_ocr, "perf_counter", lambda: next(clock))

    measured_report, timing = bench_ocr._measure_run(b"image", object())

    assert measured_report is report
    assert timing.decode_preprocess_seconds == pytest.approx(2.0)
    assert timing.ocr_seconds == pytest.approx(4.0)
    assert timing.extraction_rules_seconds == pytest.approx(4.0)
    assert timing.total_seconds == pytest.approx(10.0)
