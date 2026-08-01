from __future__ import annotations

import csv
import importlib
import importlib.util
import io
from pathlib import Path
from types import ModuleType

import pandas as pd
import pytest

from labelcheck.models import ApplicationRecord, FieldResult, LabelReport, Status

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
REPORT_FIELD_LABELS = {
    "brand_name": "Brand name",
    "class_type": "Class or type",
    "alcohol_content": "Alcohol content",
    "net_contents": "Net contents",
    "bottler": "Bottler or producer",
    "origin_country": "Country of origin",
    "government_warning": "Government warning wording",
    "government_warning_prefix": "Government warning heading",
    "government_warning_bold": "Government warning bold text",
    "government_warning_type_size": "Government warning type size",
}
FIELD_COLUMNS = tuple(
    f"{REPORT_FIELD_LABELS[field_name]} — {suffix}"
    for field_name in REPORT_FIELDS
    for suffix in (
        "result",
        "application value",
        "we read this as",
        "confidence",
        "details",
    )
)
RESULT_COLUMNS = (
    "Filename",
    "Overall result",
    "Checks that could not be run",
    "Problem",
    *FIELD_COLUMNS,
)


def _load_module(name: str) -> ModuleType:
    try:
        return importlib.import_module(name)
    except ModuleNotFoundError:
        pytest.fail(f"{name} has not been implemented")


def _application() -> ApplicationRecord:
    return ApplicationRecord(
        brand_name="Application Brand",
        class_type="Whiskey",
        alcohol_content="45% Alc./Vol. (90 Proof)",
        net_contents="750 mL",
        bottler="Example Bottler",
        origin_country=None,
    )


def _passing_report(*, unevaluated_fields: frozenset[str] = frozenset()) -> LabelReport:
    results = {
        field_name: FieldResult(
            status=(
                Status.NOT_EVALUATED if field_name in unevaluated_fields else Status.PASS
            ),
            expected=(
                "Application Brand" if field_name == "brand_name" else f"Expected {field_name}"
            ),
            extracted=(
                None
                if field_name in unevaluated_fields
                else "Label Brand" if field_name == "brand_name" else f"Read {field_name}"
            ),
            confidence=None if field_name in unevaluated_fields else 0.94,
            crop=b"crop",
            detail=(
                "This check could not be run."
                if field_name in unevaluated_fields
                else (
                    "Brand matched after normalization."
                    if field_name == "brand_name"
                    else "Deterministic complete report."
                )
            ),
        )
        for field_name in REPORT_FIELDS
    }
    return LabelReport(results)


def test_results_dataframe_has_a_stable_complete_shape_and_failure_first_order() -> None:
    batch = _load_module("labelcheck.batch")
    report = _load_module("labelcheck.report")
    success = batch.BatchResult(
        filename="matched.png",
        application=_application(),
        report=_passing_report(),
    )
    missing = batch.BatchResult(
        filename="missing.png",
        application=_application(),
        error="The image listed in the application CSV was not uploaded.",
    )

    frame = report.results_to_dataframe([success, missing])

    assert report.REPORT_FIELDS == REPORT_FIELDS
    assert report.REPORT_FIELD_LABELS == REPORT_FIELD_LABELS
    assert report.RESULT_COLUMNS == RESULT_COLUMNS
    assert tuple(frame.columns) == RESULT_COLUMNS
    assert frame.shape == (2, len(RESULT_COLUMNS))
    assert frame["Filename"].tolist() == ["missing.png", "matched.png"]
    assert frame["Overall result"].tolist() == ["NOT CHECKED", "PASS"]

    matched_row = frame.loc[frame["Filename"] == "matched.png"].iloc[0]
    assert matched_row["Checks that could not be run"] == ""
    assert matched_row["Brand name — result"] == "PASS"
    assert matched_row["Brand name — application value"] == "Application Brand"
    assert matched_row["Brand name — we read this as"] == "Label Brand"
    assert matched_row["Brand name — confidence"] == pytest.approx(0.94)
    assert matched_row["Brand name — details"] == "Brand matched after normalization."

    missing_row = frame.loc[frame["Filename"] == "missing.png"].iloc[0]
    assert missing_row["Checks that could not be run"] == (
        "10 checks could not be run — "
        + "; ".join(REPORT_FIELD_LABELS[field_name] for field_name in REPORT_FIELDS)
    )
    assert missing_row["Brand name — application value"] == "Application Brand"
    assert pd.isna(missing_row["Brand name — we read this as"])
    assert pd.isna(missing_row["Brand name — confidence"])


def test_dataframe_csv_export_is_in_memory_and_keeps_the_screen_columns() -> None:
    batch = _load_module("labelcheck.batch")
    report = _load_module("labelcheck.report")
    result = batch.BatchResult(
        filename="matched.png",
        application=_application(),
        report=_passing_report(
            unevaluated_fields=frozenset(
                {"government_warning_bold", "government_warning_type_size"}
            )
        ),
    )
    frame = report.results_to_dataframe([result])

    csv_bytes = report.dataframe_to_csv(frame)
    exported = pd.read_csv(io.BytesIO(csv_bytes), keep_default_na=False)

    assert isinstance(csv_bytes, bytes)
    assert tuple(exported.columns) == tuple(frame.columns)
    assert exported.shape == frame.shape
    assert exported.loc[0, "Filename"] == "matched.png"
    assert exported.loc[0, "Overall result"] == "PASS"
    assert exported.loc[0, "Checks that could not be run"] == (
        "2 checks could not be run — Government warning bold text; "
        "Government warning type size"
    )
    assert exported.loc[0, "Brand name — we read this as"] == "Label Brand"
    assert exported.loc[0, "Brand name — confidence"] == pytest.approx(0.94)


def test_unevaluated_status_uses_plain_language() -> None:
    batch = _load_module("labelcheck.batch")
    report = _load_module("labelcheck.report")
    label_report = _passing_report(
        unevaluated_fields=frozenset(REPORT_FIELDS)
    )

    frame = report.results_to_dataframe(
        [
            batch.BatchResult(
                filename="domestic.png",
                application=_application(),
                report=label_report,
            )
        ]
    )

    assert frame.loc[0, "Overall result"] == "NOT CHECKED"
    assert frame.loc[0, "Checks that could not be run"] == (
        "10 checks could not be run — "
        + "; ".join(REPORT_FIELD_LABELS[field_name] for field_name in REPORT_FIELDS)
    )
    assert frame.loc[0, "Country of origin — result"] == "NOT CHECKED"


def test_partial_report_never_appears_as_a_complete_pass() -> None:
    batch = _load_module("labelcheck.batch")
    report = _load_module("labelcheck.report")
    partial_report = LabelReport(
        {
            "brand_name": FieldResult(
                status=Status.PASS,
                expected="Application Brand",
                extracted="Label Brand",
                confidence=0.94,
                crop=b"crop",
                detail="Brand matched.",
            )
        }
    )
    result = batch.BatchResult(
        filename="partial.png",
        application=_application(),
        report=partial_report,
    )

    frame = report.results_to_dataframe([result])

    assert result.status is Status.NOT_EVALUATED
    assert frame.loc[0, "Overall result"] == "NOT CHECKED"
    assert frame.loc[0, "Checks that could not be run"] == (
        "9 checks could not be run — "
        + "; ".join(
            REPORT_FIELD_LABELS[field_name]
            for field_name in REPORT_FIELDS
            if field_name != "brand_name"
        )
    )
    assert frame.loc[0, "Class or type — result"] == "NOT CHECKED"
    assert frame.loc[0, "Class or type — details"] == "This check was not completed."


def test_unknown_unevaluated_check_is_disclosed_without_breaking_export() -> None:
    batch = _load_module("labelcheck.batch")
    report = _load_module("labelcheck.report")
    label_report = LabelReport(
        {
            "unknown_check": FieldResult(
                Status.NOT_EVALUATED,
                None,
                None,
                None,
                b"crop",
                "This check could not be run.",
            )
        }
    )

    frame = report.results_to_dataframe(
        [batch.BatchResult(filename="unknown.png", report=label_report)]
    )

    assert frame.loc[0, "Checks that could not be run"].startswith(
        "11 checks could not be run — "
    )
    assert "Unknown check" in frame.loc[0, "Checks that could not be run"]


def test_single_label_csv_lists_missing_checks_as_not_checked() -> None:
    app_path = Path(__file__).parents[1] / "app.py"
    spec = importlib.util.spec_from_file_location("labelcheck_test_app", app_path)
    assert spec is not None and spec.loader is not None
    label_app = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(label_app)
    partial_report = LabelReport(
        {
            "brand_name": FieldResult(
                Status.PASS,
                "Application Brand",
                "Label Brand",
                0.94,
                b"crop",
                "Brand matched.",
            )
        }
    )

    rows = list(csv.reader(io.StringIO(label_app._report_to_csv(partial_report).decode())))
    rows_by_check = {row[0]: row for row in rows[1:]}

    assert len(rows) == len(REPORT_FIELDS) + 1
    assert rows_by_check["Brand name"][1] == "Matches"
    assert rows_by_check["Class or type"][1] == "Not checked"
    assert rows_by_check["Class or type"][4] == "This check could not be run."


@pytest.mark.parametrize(
    ("field_name", "status", "detail"),
    [
        (
            "alcohol_content",
            Status.REVIEW,
            "Application proof 80 is inconsistent with its ABV.",
        ),
        (
            "brand_name",
            Status.REVIEW,
            "Multiple brand-name candidates were located; agent review is required.",
        ),
        (
            "net_contents",
            Status.FAIL,
            "Net contents differ by 250 mL after unit conversion.",
        ),
    ],
)
def test_single_label_non_pass_reason_reaches_the_user(
    field_name: str,
    status: Status,
    detail: str,
) -> None:
    app_path = Path(__file__).parents[1] / "app.py"
    spec = importlib.util.spec_from_file_location("labelcheck_test_app_detail", app_path)
    assert spec is not None and spec.loader is not None
    label_app = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(label_app)
    result = FieldResult(status, "expected", "extracted", None, b"crop", detail)

    assert label_app._user_detail(field_name, result) == detail
