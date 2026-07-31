from __future__ import annotations

from collections.abc import Sequence

import pandas as pd

from labelcheck.batch import VERIFICATION_FIELDS, BatchResult, sort_results
from labelcheck.models import LabelReport

REPORT_FIELDS = VERIFICATION_FIELDS
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
_FIELD_SUFFIXES = (
    "result",
    "application value",
    "we read this as",
    "confidence",
    "details",
)
_APPLICATION_FIELDS = frozenset(
    {
        "brand_name",
        "class_type",
        "alcohol_content",
        "net_contents",
        "bottler",
        "origin_country",
    }
)
_STATUS_TEXT = {
    "PASS": "PASS",
    "REVIEW": "REVIEW",
    "FAIL": "FAIL",
    "NOT_EVALUATED": "NOT CHECKED",
}
RESULT_COLUMNS = (
    "Filename",
    "Overall result",
    "Checks that could not be run",
    "Problem",
    *(
        f"{REPORT_FIELD_LABELS[field_name]} — {suffix}"
        for field_name in REPORT_FIELDS
        for suffix in _FIELD_SUFFIXES
    ),
)


def results_to_dataframe(results: Sequence[BatchResult]) -> pd.DataFrame:
    """Create one auditable row per input so reconciliation gaps stay visible."""

    records = [_result_record(result) for result in sort_results(results)]
    return pd.DataFrame.from_records(records, columns=RESULT_COLUMNS)


def dataframe_to_csv(frame: pd.DataFrame) -> bytes:
    """Return browser-ready CSV bytes without introducing a filesystem retention path."""

    return frame.to_csv(index=False, lineterminator="\n").encode("utf-8")


def _result_record(result: BatchResult) -> dict[str, object | None]:
    record: dict[str, object | None] = dict.fromkeys(RESULT_COLUMNS)
    record["Filename"] = result.filename
    record["Overall result"] = _STATUS_TEXT[result.status.value]
    record["Checks that could not be run"] = _unevaluated_disclosure(result.report)
    record["Problem"] = result.error

    for field_name in REPORT_FIELDS:
        label = REPORT_FIELD_LABELS[field_name]
        field_result = result.report.results.get(field_name) if result.report is not None else None
        if field_result is not None:
            record[f"{label} — result"] = _STATUS_TEXT[field_result.status.value]
            record[f"{label} — application value"] = field_result.expected
            record[f"{label} — we read this as"] = field_result.extracted
            record[f"{label} — confidence"] = field_result.confidence
            record[f"{label} — details"] = field_result.detail
        else:
            record[f"{label} — result"] = _STATUS_TEXT["NOT_EVALUATED"]
            record[f"{label} — details"] = "This check was not completed."
            if result.application is not None and field_name in _APPLICATION_FIELDS:
                record[f"{label} — application value"] = getattr(result.application, field_name)
    return record


def _unevaluated_disclosure(report: LabelReport | None) -> str:
    if report is None:
        field_names = REPORT_FIELDS
    else:
        explicitly_unevaluated = report.unevaluated_checks
        field_names = tuple(
            field_name
            for field_name in REPORT_FIELDS
            if field_name not in report.results or field_name in explicitly_unevaluated
        ) + tuple(
            field_name
            for field_name in explicitly_unevaluated
            if field_name not in REPORT_FIELD_LABELS
        )
    labels = [
        REPORT_FIELD_LABELS.get(field_name, field_name.replace("_", " ").capitalize())
        for field_name in field_names
    ]
    if not labels:
        return ""
    count = len(labels)
    noun = "check" if count == 1 else "checks"
    return f"{count} {noun} could not be run — {'; '.join(labels)}"
