import pytest

from labelcheck.models import Status
from labelcheck.rules.origin import verify


def test_domestic_record_origin_is_not_evaluated_never_passed() -> None:
    result = verify(extracted=None, expected=None)

    assert result.status is Status.NOT_EVALUATED
    assert result.confidence is None
    assert "domestic" in result.detail.lower()


def test_blank_domestic_origin_is_not_evaluated_even_if_label_has_text() -> None:
    result = verify(extracted="France", expected="   ")

    assert result.status is Status.NOT_EVALUATED


@pytest.mark.parametrize(
    "placeholder",
    ["N/A", "n/a", "NA", "none", "None", "-", "--", r"n\a", "not applicable", "domestic"],
)
def test_origin_placeholders_are_not_evaluated_as_imports(placeholder: str) -> None:
    result = verify(extracted="Product of France", expected=placeholder)

    assert result.status is Status.NOT_EVALUATED
    assert result.confidence is None
    assert "blank or placeholder" in result.detail.lower()


def test_unlisted_application_marker_is_not_treated_as_a_domestic_placeholder() -> None:
    result = verify(extracted="Product of France", expected="?")

    assert result.status is Status.FAIL


def test_extracted_placeholder_text_is_compared_for_a_required_import() -> None:
    result = verify(extracted="Product of N/A", expected="France")

    assert result.status is Status.FAIL


def test_import_origin_case_and_punctuation_variation_passes() -> None:
    result = verify(extracted="Product of FRANCE.", expected="Product of France")

    assert result.status is Status.PASS


def test_import_origin_label_boilerplate_matches_manifest_country_value() -> None:
    result = verify(extracted="Product of FRANCE.", expected="France")

    assert result.status is Status.PASS


def test_import_origin_mismatch_fails() -> None:
    result = verify(extracted="Product of Spain", expected="Product of France")

    assert result.status is Status.FAIL


def test_required_import_origin_not_located_is_not_evaluated() -> None:
    result = verify(extracted="", expected="Product of France")

    assert result.status is Status.NOT_EVALUATED
    assert "not located" in result.detail.lower()


def test_origin_result_preserves_raw_values_and_crop() -> None:
    crop = object()

    result = verify("France", "France", crop=crop)

    assert result.expected == "France"
    assert result.extracted == "France"
    assert result.crop is crop
