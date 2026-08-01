import io
from dataclasses import replace

import cv2
import numpy as np
import pytest
from fixture_factory import make_label, sample_application_record
from PIL import Image

from labelcheck import preprocess as preprocess_module
from labelcheck.models import FieldResult, LabelReport, Status, TextBlock
from labelcheck.ocr import OcrEngine, OcrError, get_engine, warm
from labelcheck.pipeline import verify
from labelcheck.preprocess import assess_image_quality, preprocess_image

EXPECTED_REPORT_FIELDS = {
    "brand_name",
    "class_type",
    "alcohol_content",
    "net_contents",
    "bottler",
    "origin_country",
    "government_warning",
    "government_warning_prefix",
    "government_warning_bold",
    "government_warning_type_size",
}


@pytest.fixture(scope="module")
def clean_report() -> LabelReport:
    warm()
    return verify(make_label(), sample_application_record())


@pytest.mark.slow
def test_clean_control_fixture_verifies_against_matching_application(
    clean_report: LabelReport,
) -> None:
    report = clean_report

    assert set(report.results) == EXPECTED_REPORT_FIELDS
    assert all(isinstance(result, FieldResult) for result in report.results.values())
    assert all(isinstance(result.crop, bytes) and result.crop for result in report.results.values())

    for field_name in (
        "brand_name",
        "class_type",
        "alcohol_content",
        "net_contents",
        "bottler",
        "government_warning",
        "government_warning_prefix",
    ):
        assert report.results[field_name].status is Status.PASS

    assert report.results["origin_country"].status is Status.NOT_EVALUATED
    assert report.results["government_warning_bold"].status is Status.NOT_EVALUATED
    assert report.results["government_warning_type_size"].status is Status.NOT_EVALUATED
    assert report.overall_status is Status.PASS
    assert report.unevaluated_checks == (
        "origin_country",
        "government_warning_bold",
        "government_warning_type_size",
    )


@pytest.mark.slow
def test_no_field_passes_without_evidence_that_was_evaluated(
    clean_report: LabelReport,
) -> None:
    for result in clean_report.results.values():
        if result.status is Status.PASS:
            assert result.extracted
            assert result.confidence is not None
            assert result.crop


def test_domestic_origin_stays_not_evaluated_when_ocr_finds_conflicting_origin_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    origin_blocks = [
        TextBlock(
            "Product of Scotland",
            ((20.0, 20.0), (240.0, 20.0), (240.0, 45.0), (20.0, 45.0)),
            0.98,
        ),
        TextBlock(
            "Made in Canada",
            ((20.0, 60.0), (210.0, 60.0), (210.0, 85.0), (20.0, 85.0)),
            0.97,
        ),
    ]
    monkeypatch.setattr("labelcheck.pipeline.ocr.recognize", lambda _image: origin_blocks)

    report = verify(make_label(), sample_application_record())

    assert report.results["origin_country"].status is Status.NOT_EVALUATED


def test_imported_origin_conflict_requires_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    origin_blocks = [
        TextBlock(
            "Product of Scotland",
            ((20.0, 20.0), (240.0, 20.0), (240.0, 45.0), (20.0, 45.0)),
            0.98,
        ),
        TextBlock(
            "Made in Canada",
            ((20.0, 60.0), (210.0, 60.0), (210.0, 85.0), (20.0, 85.0)),
            0.97,
        ),
    ]
    monkeypatch.setattr("labelcheck.pipeline.ocr.recognize", lambda _image: origin_blocks)
    expected = replace(sample_application_record(), origin_country="Scotland")

    report = verify(make_label(), expected)

    assert report.results["origin_country"].status is Status.REVIEW


def test_bottler_address_ocr_error_routes_to_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bottler_block = TextBlock(
        "Bottler: Bottled by Old Tom Distillery, Bardstovvn, Kentucky",
        ((20.0, 20.0), (760.0, 20.0), (760.0, 50.0), (20.0, 50.0)),
        0.98,
    )
    monkeypatch.setattr("labelcheck.pipeline.ocr.recognize", lambda _image: [bottler_block])

    report = verify(make_label(), sample_application_record())

    assert report.results["bottler"].status is Status.REVIEW


@pytest.mark.slow
def test_ocr_engine_is_process_stable() -> None:
    assert get_engine() is get_engine()


def test_clean_preprocessing_is_conditional_and_low_resolution_is_upscaled() -> None:
    clean_bytes = make_label()
    with Image.open(io.BytesIO(clean_bytes)) as source:
        expected_clean = cv2.cvtColor(np.asarray(source.convert("RGB")), cv2.COLOR_RGB2BGR)

    clean = preprocess_image(clean_bytes)
    quality = assess_image_quality(clean)
    low_resolution = preprocess_image(make_label(low_resolution=True))

    assert np.array_equal(clean, expected_clean)
    assert not quality.needs_deskew
    assert not quality.needs_perspective_correction
    assert not quality.needs_clahe
    assert not quality.needs_upscale
    assert min(low_resolution.shape[:2]) == 736


def test_clean_image_returns_before_corrective_helpers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_transform(_image: np.ndarray) -> np.ndarray:
        raise AssertionError("clean image reached a corrective transform")

    monkeypatch.setattr(preprocess_module, "_downscale_if_needed", unexpected_transform)
    monkeypatch.setattr(preprocess_module, "_upscale_if_needed", unexpected_transform)

    processed = preprocess_image(make_label())

    assert processed.shape[:2] == (900, 1400)


def test_oversized_image_is_capped_before_corrective_transforms(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image = np.full((1800, 2800, 3), 255, dtype=np.uint8)
    successful, encoded = cv2.imencode(".png", image)
    assert successful

    real_assess = preprocess_module.assess_image_quality

    def force_deskew(frame: np.ndarray):
        return replace(
            real_assess(frame),
            skew_angle_degrees=3.0,
            needs_deskew=True,
            needs_perspective_correction=False,
            needs_clahe=False,
        )

    deskew_shapes: list[tuple[int, int]] = []

    def record_deskew(frame: np.ndarray, _angle: float) -> np.ndarray:
        deskew_shapes.append(frame.shape[:2])
        return frame

    monkeypatch.setattr(preprocess_module, "assess_image_quality", force_deskew)
    monkeypatch.setattr(preprocess_module, "_deskew", record_deskew)

    processed = preprocess_image(encoded.tobytes())

    assert deskew_shapes
    assert max(deskew_shapes[0]) == 1400
    assert max(processed.shape[:2]) == 1400


def test_extreme_aspect_ratio_never_upscales_past_the_ocr_cap() -> None:
    image = np.full((100, 5000, 3), 255, dtype=np.uint8)
    successful, encoded = cv2.imencode(".png", image)
    assert successful

    processed = preprocess_image(encoded.tobytes())

    assert max(processed.shape[:2]) == 1400


def test_exif_orientation_is_applied_before_quality_gates() -> None:
    image = Image.new("RGB", (1000, 800), "white")
    exif = Image.Exif()
    exif[274] = 6
    encoded = io.BytesIO()
    image.save(encoded, format="JPEG", exif=exif)

    processed = preprocess_image(encoded.getvalue())

    assert processed.shape[:2] == (1000, 800)


def test_rotated_fixture_is_deskewed_only_when_the_quality_gate_detects_skew() -> None:
    rotated_bytes = make_label(rotation_degrees=5.0)
    raw = cv2.imdecode(np.frombuffer(rotated_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)

    before = assess_image_quality(raw)
    corrected = preprocess_image(rotated_bytes)
    after = assess_image_quality(corrected)

    assert before.needs_deskew
    assert abs(after.skew_angle_degrees) < abs(before.skew_angle_degrees)


def test_largest_distorted_quadrilateral_is_perspective_corrected() -> None:
    image = np.full((900, 900, 3), 255, dtype=np.uint8)
    quadrilateral = np.asarray(((150, 100), (760, 180), (700, 770), (220, 700)), dtype=np.int32)
    cv2.fillConvexPoly(image, quadrilateral, (232, 232, 232))
    cv2.polylines(image, [quadrilateral], True, (10, 10, 10), thickness=8)
    successful, encoded = cv2.imencode(".png", image)
    assert successful

    before = assess_image_quality(image)
    corrected = preprocess_image(encoded.tobytes())

    assert before.needs_perspective_correction
    assert corrected.shape[:2] != image.shape[:2]


def test_ocr_wrapper_converts_valid_rows_and_skips_malformed_rows() -> None:
    class Backend:
        def __call__(self, _image):
            return (
                [
                    [
                        [[1.0, 2.0], [11.0, 2.0], [11.0, 8.0], [1.0, 8.0]],
                        " Keep Case ",
                        0.94,
                    ],
                    ["malformed"],
                ],
                {"total": 0.01},
            )

    blocks = OcrEngine(backend=Backend()).recognize(np.zeros((20, 30, 3), dtype=np.uint8))

    assert len(blocks) == 1
    assert blocks[0].text == " Keep Case "
    assert blocks[0].bbox[2] == (11.0, 8.0)
    assert blocks[0].confidence == pytest.approx(0.94)


def test_ocr_wrapper_distinguishes_backend_failure_from_no_text() -> None:
    class BrokenBackend:
        def __call__(self, _image):
            raise RuntimeError("backend failed")

    engine = OcrEngine(backend=BrokenBackend())

    with pytest.raises(OcrError, match="OCR inference failed"):
        engine.recognize(np.zeros((20, 30, 3), dtype=np.uint8))


def test_default_ocr_backend_uses_measured_runtime_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class Backend:
        def __call__(self, _image):
            return None, None

    def build_backend(**kwargs: object) -> Backend:
        captured.update(kwargs)
        return Backend()

    monkeypatch.setattr("labelcheck.ocr.RapidOCR", build_backend)

    OcrEngine()

    assert captured == {
        "det_limit_side_len": 736,
        "intra_op_num_threads": 6,
        "max_side_len": 1400,
        "use_cls": False,
    }
