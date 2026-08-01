import pytest

from labelcheck.models import Status
from labelcheck.rules.bottler import verify


def test_bottling_prefix_is_cosmetic_for_an_exact_name_match() -> None:
    crop = object()

    result = verify(
        "BOTTLED BY STONE'S THROW DISTILLERY",
        "Stone's Throw Distillery",
        crop=crop,
    )

    assert result.status is Status.PASS
    assert result.confidence == 100.0
    assert result.crop is crop


def test_label_address_absent_from_application_requires_review_not_failure() -> None:
    result = verify(
        "Bottled by X, City, State",
        "X",
    )

    assert result.status is Status.REVIEW


def test_one_character_address_ocr_error_requires_review_not_failure() -> None:
    result = verify(
        "Bottled by Stone's Throw Distillery, Bardstovvn, Kentucky",
        "Stone's Throw Distillery, Bardstown, Kentucky",
    )

    assert result.status is Status.REVIEW


@pytest.mark.parametrize(
    ("extracted", "expected"),
    [
        ("Bottled by Acme Distillery, Denver, CO", "Acme Distillery, Denver"),
        ("Bottled by Acme Distillery, LLC", "Acme Distillery"),
    ],
)
def test_omitted_bottler_tokens_require_review(extracted: str, expected: str) -> None:
    result = verify(extracted, expected)

    assert result.status is Status.REVIEW


def test_genuinely_different_bottler_fails() -> None:
    result = verify(
        "Bottled for Harbor Light Imports, Seattle, Washington",
        "Stone's Throw Distillery, Bardstown, Kentucky",
    )

    assert result.status is Status.FAIL
