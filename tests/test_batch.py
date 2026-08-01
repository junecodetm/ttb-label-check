from __future__ import annotations

import csv
import importlib
import io
import threading
import time
from pathlib import Path
from types import ModuleType

import numpy as np
import pytest
from streamlit.testing.v1 import AppTest

import labelcheck.ocr
import labelcheck.pipeline
from labelcheck.models import FieldResult, LabelReport, Status

MANIFEST_COLUMNS = (
    "filename",
    "brand_name",
    "class_type",
    "alcohol_content",
    "net_contents",
    "bottler",
    "origin_country",
)
REPORT_FIELDS = (
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
)


def _batch_module() -> ModuleType:
    try:
        return importlib.import_module("labelcheck.batch")
    except ModuleNotFoundError:
        pytest.fail("labelcheck.batch has not been implemented")


def _manifest_bytes(
    rows: list[tuple[str, ...]], header: tuple[str, ...] = MANIFEST_COLUMNS
) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(header)
    writer.writerows(rows)
    return output.getvalue().encode("utf-8")


def _manifest_row(filename: str, index: int, *, origin_country: str = "") -> tuple[str, ...]:
    return (
        filename,
        f"Brand {index}",
        "Whiskey",
        "45% Alc./Vol. (90 Proof)",
        "750 mL",
        f"Bottler {index}",
        origin_country,
    )


def _label_report(
    status: Status,
    *,
    expected_brand: str = "Expected brand",
    extracted_brand: str = "Read brand",
    confidence: float = 0.91,
    crop: object = b"crop",
    unevaluated_fields: frozenset[str] = frozenset(),
) -> LabelReport:
    results = {
        field_name: FieldResult(
            status=(
                Status.NOT_EVALUATED if field_name in unevaluated_fields else status
            ),
            expected=expected_brand if field_name == "brand_name" else f"Expected {field_name}",
            extracted=(
                None
                if field_name in unevaluated_fields
                else extracted_brand if field_name == "brand_name" else f"Read {field_name}"
            ),
            confidence=None if field_name in unevaluated_fields else confidence,
            crop=crop,
            detail=(
                "This check could not be run."
                if field_name in unevaluated_fields
                else "Deterministic fake verification result."
            ),
        )
        for field_name in REPORT_FIELDS
    }
    return LabelReport(results)


def test_manifest_parser_preserves_the_exact_schema_and_domestic_origin() -> None:
    batch = _batch_module()

    rows = batch.parse_manifest(_manifest_bytes([_manifest_row("label.png", 1)]))

    assert batch.MANIFEST_COLUMNS == MANIFEST_COLUMNS
    assert len(rows) == 1
    assert rows[0].filename == "label.png"
    assert rows[0].application.origin_country is None


def test_manifest_parser_rejects_reordered_headers() -> None:
    batch = _batch_module()
    reordered = (
        "brand_name",
        "filename",
        "class_type",
        "alcohol_content",
        "net_contents",
        "bottler",
        "origin_country",
    )

    with pytest.raises(batch.ManifestError, match="columns.*order"):
        batch.parse_manifest(_manifest_bytes([], reordered))


def test_filename_reconciliation_is_case_insensitive() -> None:
    batch = _batch_module()
    manifest = batch.parse_manifest(_manifest_bytes([_manifest_row("MiXeD.PnG", 1)]))
    calls = 0

    def fake_verify(image_bytes: bytes, application: object) -> LabelReport:
        nonlocal calls
        calls += 1
        assert image_bytes == b"image"
        assert application is manifest[0].application
        return _label_report(Status.PASS)

    results = batch.run_batch(
        {"mixed.png": b"image"},
        manifest,
        verify_callable=fake_verify,
    )

    assert calls == 1
    assert len(results) == 1
    assert results[0].filename == "MiXeD.PnG"
    assert results[0].error is None


def test_twenty_image_batch_accounts_for_every_input_and_orders_triage_queue() -> None:
    batch = _batch_module()
    images = {f"label_{index:02}.png": f"image-{index}".encode() for index in range(20)}
    manifest_rows = [
        _manifest_row("LABEL_00.PNG" if index == 0 else f"label_{index:02}.png", index)
        for index in range(19)
    ]
    manifest_rows.append(_manifest_row("missing.png", 99, origin_country="France"))
    manifest = batch.parse_manifest(_manifest_bytes(manifest_rows))
    verified_brands: list[str] = []
    worker_names: set[str] = set()
    calls_lock = threading.Lock()
    progress_updates: list[tuple[int, int]] = []

    def fake_verify(image_bytes: bytes, application: object) -> LabelReport:
        del image_bytes
        brand_name = application.brand_name
        index = int(brand_name.removeprefix("Brand "))
        time.sleep((19 - index) * 0.002)
        with calls_lock:
            verified_brands.append(brand_name)
            worker_names.add(threading.current_thread().name)
        status = (Status.FAIL, Status.REVIEW, Status.PASS)[index % 3]
        return _label_report(status)

    results = batch.run_batch(
        images,
        manifest,
        verify_callable=fake_verify,
        max_workers=50,
        progress_callback=lambda completed, total: progress_updates.append((completed, total)),
    )

    missing_image = next(result for result in results if result.filename == "missing.png")
    missing_manifest = next(result for result in results if result.filename == "label_19.png")
    assert missing_image.status is Status.NOT_EVALUATED
    assert "not uploaded" in missing_image.error.lower()
    assert missing_manifest.status is Status.NOT_EVALUATED
    assert "no matching manifest row" in missing_manifest.error.lower()
    assert len(results) == len(manifest) + 1 == 21
    assert len(verified_brands) == 19

    severity = {
        Status.FAIL: 0,
        Status.REVIEW: 1,
        Status.NOT_EVALUATED: 2,
        Status.PASS: 3,
    }
    ranks = [0 if result.error is not None else severity[result.status] for result in results]
    assert ranks == sorted(ranks)
    expected_order = [
        *("LABEL_00.PNG" if index == 0 else f"label_{index:02}.png" for index in range(0, 19, 3)),
        "missing.png",
        "label_19.png",
        *(f"label_{index:02}.png" for index in range(1, 19, 3)),
        *(f"label_{index:02}.png" for index in range(2, 19, 3)),
    ]
    assert [result.filename for result in results] == expected_order
    assert progress_updates[-1] == (21, 21)
    assert [completed for completed, _ in progress_updates] == sorted(
        completed for completed, _ in progress_updates
    )
    assert 1 < len(worker_names) <= 8


def test_results_sort_fail_review_not_evaluated_then_pass_with_errors_as_failures() -> None:
    batch = _batch_module()
    results = [
        batch.BatchResult(filename="pass.png", report=_label_report(Status.PASS)),
        batch.BatchResult(
            filename="nothing-ran.png", report=_label_report(Status.NOT_EVALUATED)
        ),
        batch.BatchResult(filename="review.png", report=_label_report(Status.REVIEW)),
        batch.BatchResult(filename="missing.png", error="Image not uploaded."),
        batch.BatchResult(filename="fail.png", report=_label_report(Status.FAIL)),
    ]

    ordered = batch.sort_results(results)

    assert [result.filename for result in ordered] == [
        "missing.png",
        "fail.png",
        "review.png",
        "nothing-ran.png",
        "pass.png",
    ]


def test_batch_entry_is_separate_while_single_label_stays_the_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(labelcheck.ocr, "warm", lambda: object())
    app_path = Path(__file__).parents[1] / "app.py"

    app = AppTest.from_file(str(app_path), default_timeout=10).run()

    assert not app.exception
    assert [title.value for title in app.title] == ["Check an alcohol label"]
    assert app.button[0].label == "Check label"
    batch_entry = next(button for button in app.button if button.label == "Check many labels")

    batch_entry.click().run()

    assert not app.exception
    assert [title.value for title in app.title] == ["Check many alcohol labels"]
    assert app.button[0].label == "Back to one label"
    assert [uploader.label for uploader in app.get("file_uploader")] == [
        "PNG or JPEG label images",
        "Application values CSV",
    ]

    app.button[0].click().run()

    assert not app.exception
    assert [title.value for title in app.title] == ["Check an alcohol label"]


def test_batch_submission_renders_progress_table_export_and_crop_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(labelcheck.ocr, "warm", lambda: object())
    verified: list[str] = []

    def fake_verify(image_bytes: bytes, application: object) -> LabelReport:
        assert image_bytes == b"image"
        verified.append(application.brand_name)
        return _label_report(
            Status.PASS,
            expected_brand=application.brand_name,
            extracted_brand="Brand 1",
            confidence=99.0,
            crop=np.zeros((4, 4, 3), dtype=np.uint8),
            unevaluated_fields=frozenset(
                {"government_warning_bold", "government_warning_type_size"}
            ),
        )

    monkeypatch.setattr(labelcheck.pipeline, "verify", fake_verify)
    app_path = Path(__file__).parents[1] / "app.py"
    app = AppTest.from_file(str(app_path), default_timeout=10).run()
    next(button for button in app.button if button.label == "Check many labels").click().run()
    uploaders = app.get("file_uploader")
    uploaders[0].set_value([("label.png", b"image", "image/png")])
    uploaders[1].set_value(
        (
            "applications.csv",
            _manifest_bytes([_manifest_row("label.png", 1)]),
            "text/csv",
        )
    )

    next(button for button in app.button if button.label == "Check all labels").click().run()

    assert not app.exception
    assert verified == ["Brand 1"]
    assert len(app.dataframe) == 1
    frame = app.dataframe[0].value
    assert frame.loc[0, "Filename"] == "label.png"
    assert frame.loc[0, "Overall result"] == "PASS"
    assert frame.loc[0, "Checks that could not be run"] == (
        "2 checks could not be run — Government warning bold text; "
        "Government warning type size"
    )
    assert frame.loc[0, "Brand name — we read this as"] == "Brand 1"
    assert app.download_button[0].label == "Download all results as CSV"
    assert any("Completed 1 of 1 labels" in message.value for message in app.success)
    assert any(
        message.value == "2 checks could not be run — see below." for message in app.info
    )
    assert "Evidence for label.png" in [subheader.value for subheader in app.subheader]
    assert len(app.image) == len(REPORT_FIELDS)


def test_single_label_passing_overall_discloses_checks_that_could_not_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(labelcheck.ocr, "warm", lambda: object())

    def fake_verify(image_bytes: bytes, application: object) -> LabelReport:
        assert image_bytes == b"image"
        return _label_report(
            Status.PASS,
            expected_brand=application.brand_name,
            crop=np.zeros((4, 4, 3), dtype=np.uint8),
            unevaluated_fields=frozenset(
                {"government_warning_bold", "government_warning_type_size"}
            ),
        )

    monkeypatch.setattr(labelcheck.pipeline, "verify", fake_verify)
    app_path = Path(__file__).parents[1] / "app.py"
    app = AppTest.from_file(str(app_path), default_timeout=10).run()
    app.get("file_uploader")[0].set_value(("label.png", b"image", "image/png"))
    values = (
        "Brand 1",
        "Whiskey",
        "45% Alc./Vol. (90 Proof)",
        "750 mL",
        "Bottler 1",
    )
    for index, value in enumerate(values):
        app.text_input[index].set_value(value)

    next(button for button in app.button if button.label == "Check label").click().run()

    assert not app.exception
    assert any(
        message.value == "Overall: All completed checks match the application."
        for message in app.success
    )
    assert [message.value for message in app.info] == [
        "2 checks could not be run — see below."
    ]


def test_single_label_review_renders_the_rule_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(labelcheck.ocr, "warm", lambda: object())
    detail = "Multiple brand-name candidates were located; agent review is required."

    def fake_verify(image_bytes: bytes, application: object) -> LabelReport:
        assert image_bytes == b"image"
        passing_report = _label_report(
            Status.PASS,
            expected_brand=application.brand_name,
            crop=np.zeros((4, 4, 3), dtype=np.uint8),
        )
        results = dict(passing_report.results)
        results["brand_name"] = FieldResult(
            Status.REVIEW,
            application.brand_name,
            "Read brand candidate",
            None,
            np.zeros((4, 4, 3), dtype=np.uint8),
            detail,
        )
        return LabelReport(results)

    monkeypatch.setattr(labelcheck.pipeline, "verify", fake_verify)
    app_path = Path(__file__).parents[1] / "app.py"
    app = AppTest.from_file(str(app_path), default_timeout=10).run()
    app.get("file_uploader")[0].set_value(("label.png", b"image", "image/png"))
    for index, value in enumerate(
        (
            "Brand 1",
            "Whiskey",
            "45% Alc./Vol. (90 Proof)",
            "750 mL",
            "Bottler 1",
        )
    ):
        app.text_input[index].set_value(value)

    next(button for button in app.button if button.label == "Check label").click().run()

    assert not app.exception
    assert detail in [message.value for message in app.markdown]


def test_batch_submission_explains_missing_inputs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(labelcheck.ocr, "warm", lambda: object())
    app_path = Path(__file__).parents[1] / "app.py"
    app = AppTest.from_file(str(app_path), default_timeout=10).run()
    next(button for button in app.button if button.label == "Check many labels").click().run()

    next(button for button in app.button if button.label == "Check all labels").click().run()

    assert not app.exception
    assert [message.value for message in app.error] == [
        "Upload the application values CSV, then choose Check all labels again. "
        "You may leave the image list empty to see which files are missing."
    ]


def test_manifest_without_images_renders_every_missing_image_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(labelcheck.ocr, "warm", lambda: object())
    app_path = Path(__file__).parents[1] / "app.py"
    app = AppTest.from_file(str(app_path), default_timeout=10).run()
    next(button for button in app.button if button.label == "Check many labels").click().run()
    app.get("file_uploader")[1].set_value(
        (
            "applications.csv",
            _manifest_bytes(
                [
                    _manifest_row("missing-one.png", 1),
                    _manifest_row("missing-two.png", 2),
                ]
            ),
            "text/csv",
        )
    )

    next(button for button in app.button if button.label == "Check all labels").click().run()

    assert not app.exception
    assert not app.error
    assert len(app.dataframe) == 1
    frame = app.dataframe[0].value
    assert frame["Filename"].tolist() == ["missing-one.png", "missing-two.png"]
    assert frame["Overall result"].tolist() == ["NOT CHECKED", "NOT CHECKED"]
    assert all("not uploaded" in problem.lower() for problem in frame["Problem"])
