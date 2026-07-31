from dataclasses import fields

from labelcheck.config import GOVERNMENT_WARNING
from labelcheck.models import ApplicationRecord, FieldResult, LabelReport, Status, TextBlock
from labelcheck.rules.alcohol import verify as verify_alcohol
from labelcheck.rules.brand import verify as verify_brand
from labelcheck.rules.net_contents import verify as verify_net_contents
from labelcheck.rules.warning import verify as verify_warning
from labelcheck.rules.warning import verify_prefix

VERIFICATION_FIELDS = (
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


def test_stones_throw_apostrophe_and_case_variation_passes() -> None:
    result = verify_brand(extracted="STONE'S THROW", expected="Stone's Throw")

    assert result.status is Status.PASS


def test_title_case_government_warning_prefix_fails() -> None:
    title_case_warning = GOVERNMENT_WARNING.replace("GOVERNMENT WARNING:", "Government Warning:")

    result = verify_prefix(extracted=title_case_warning)

    assert result.status is Status.FAIL


def test_altered_warning_wording_fails_with_identifying_diff() -> None:
    altered_warning = GOVERNMENT_WARNING.replace(
        "may cause health problems", "may cause serious health problems"
    )

    result = verify_warning(extracted=altered_warning)

    assert result.status is Status.FAIL
    assert "serious" in result.detail


def test_matching_45_percent_abv_and_90_proof_cross_check_passes() -> None:
    result = verify_alcohol(
        extracted="45% Alc./Vol. (90 Proof)",
        expected="45% Alc./Vol. (90 Proof)",
        beverage_class="distilled spirits",
    )

    assert result.status is Status.PASS


def test_45_percent_abv_with_80_proof_is_flagged() -> None:
    result = verify_alcohol(
        extracted="45% Alc./Vol. (80 Proof)",
        expected="45% Alc./Vol. (90 Proof)",
        beverage_class="distilled spirits",
    )

    assert result.status is not Status.PASS
    assert "proof" in result.detail.lower()


def test_750_milliliters_and_point_75_liters_pass() -> None:
    result = verify_net_contents(extracted="750 mL", expected="0.75 L")

    assert result.status is Status.PASS


def test_status_and_application_record_keep_the_manifest_contract() -> None:
    assert [status.value for status in Status] == [
        "PASS",
        "REVIEW",
        "FAIL",
        "NOT_EVALUATED",
    ]
    assert [item.name for item in fields(ApplicationRecord)] == [
        "brand_name",
        "class_type",
        "alcohol_content",
        "net_contents",
        "bottler",
        "origin_country",
    ]


def test_field_result_keeps_every_required_member_even_without_a_crop() -> None:
    result = FieldResult(
        status=Status.NOT_EVALUATED,
        expected="expected",
        extracted=None,
        confidence=None,
        crop=None,
        detail="No image evidence exists in the pure-logic phase.",
    )

    assert [item.name for item in fields(FieldResult)] == [
        "status",
        "expected",
        "extracted",
        "confidence",
        "crop",
        "detail",
    ]
    assert result.crop is None


def test_text_block_remains_a_dependency_free_future_ocr_contract() -> None:
    block = TextBlock(
        text="750 mL",
        bbox=((0.0, 0.0), (10.0, 0.0), (10.0, 4.0), (0.0, 4.0)),
        confidence=0.98,
    )

    assert block.text == "750 mL"
    assert block.bbox[2] == (10.0, 4.0)


def test_report_rollup_passes_evaluated_checks_and_discloses_unevaluated_names() -> None:
    passing = FieldResult(Status.PASS, "a", "a", 100.0, None, "Matched.")
    unevaluated = FieldResult(Status.NOT_EVALUATED, "b", None, None, None, "Could not evaluate.")
    review = FieldResult(Status.REVIEW, "c", "near", 80.0, None, "Needs review.")
    results = dict.fromkeys(VERIFICATION_FIELDS, passing)
    results["origin_country"] = unevaluated

    report = LabelReport(results)

    assert report.overall_status is Status.PASS
    assert report.unevaluated_checks == ("origin_country",)

    results["class_type"] = review
    assert LabelReport(results).overall_status is Status.REVIEW


def test_report_rollup_is_not_evaluated_when_no_check_ran() -> None:
    unevaluated = FieldResult(Status.NOT_EVALUATED, "b", None, None, None, "Could not evaluate.")

    assert LabelReport({}).overall_status is Status.NOT_EVALUATED
    assert LabelReport({"origin": unevaluated}).overall_status is Status.NOT_EVALUATED


def test_report_rollup_failure_wins_over_unevaluated_checks() -> None:
    passing = FieldResult(Status.PASS, "a", "a", 100.0, None, "Matched.")
    unevaluated = FieldResult(Status.NOT_EVALUATED, "b", None, None, None, "Could not evaluate.")
    review = FieldResult(Status.REVIEW, "c", "near", 80.0, None, "Needs review.")
    failure = FieldResult(Status.FAIL, "d", "wrong", 0.0, None, "Mismatch.")
    results = dict.fromkeys(VERIFICATION_FIELDS, passing)
    results["origin_country"] = unevaluated
    results["class_type"] = review
    results["government_warning"] = failure

    assert LabelReport(results).overall_status is Status.FAIL
