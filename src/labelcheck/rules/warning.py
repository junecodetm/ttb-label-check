from labelcheck.config import (
    EXACT_MATCH_CONFIDENCE,
    GOVERNMENT_WARNING,
    GOVERNMENT_WARNING_PREFIX,
    MISMATCH_CONFIDENCE,
    WARNING_BOLD_EXPECTATION,
    WARNING_TYPE_SIZE_EXPECTATION,
)
from labelcheck.models import FieldResult, Status
from labelcheck.normalize import extract_warning_prefix, normalize_warning_text, word_level_diff


def verify(
    extracted: str | None,
    *,
    crop: object | None = None,
) -> FieldResult:
    """Use normalized exact equality because statutory wording is not a fuzzy field."""

    expected = GOVERNMENT_WARNING
    if extracted is None:
        return FieldResult(
            Status.NOT_EVALUATED,
            expected,
            extracted,
            None,
            crop,
            "Government warning text was not located, so the check was not evaluated.",
        )

    normalized_extracted = normalize_warning_text(extracted)
    normalized_expected = normalize_warning_text(expected)
    if not normalized_extracted:
        return FieldResult(
            Status.NOT_EVALUATED,
            expected,
            extracted,
            None,
            crop,
            "Government warning text was not located, so the check was not evaluated.",
        )
    if normalized_extracted == normalized_expected:
        return FieldResult(
            Status.PASS,
            expected,
            extracted,
            EXACT_MATCH_CONFIDENCE,
            crop,
            "Government warning wording matches the statutory text exactly after OCR-safe "
            "normalization.",
        )

    difference = word_level_diff(normalized_expected, normalized_extracted)
    if not difference:
        difference = "normalized text differs at the character level"
    return FieldResult(
        Status.FAIL,
        expected,
        extracted,
        MISMATCH_CONFIDENCE,
        crop,
        f"Government warning deviation: {difference}.",
    )


def verify_prefix(
    extracted: str | None,
    *,
    crop: object | None = None,
) -> FieldResult:
    """Report capitalization as its own rejection reason instead of hiding it in text."""

    if extracted is None or not normalize_warning_text(extracted):
        return FieldResult(
            Status.NOT_EVALUATED,
            GOVERNMENT_WARNING_PREFIX,
            extracted,
            None,
            crop,
            "Government warning prefix was not located, so the check was not evaluated.",
        )

    extracted_prefix = extract_warning_prefix(extracted)
    if extracted_prefix == GOVERNMENT_WARNING_PREFIX:
        return FieldResult(
            Status.PASS,
            GOVERNMENT_WARNING_PREFIX,
            extracted_prefix,
            EXACT_MATCH_CONFIDENCE,
            crop,
            "The GOVERNMENT WARNING: prefix is uppercase and exact.",
        )
    return FieldResult(
        Status.FAIL,
        GOVERNMENT_WARNING_PREFIX,
        extracted_prefix,
        MISMATCH_CONFIDENCE,
        crop,
        "Government warning prefix deviation: "
        f"{word_level_diff(GOVERNMENT_WARNING_PREFIX, extracted_prefix)}.",
    )


def verify_bold(*, crop: object | None = None) -> FieldResult:
    """Stay honest because OCR text contains no evidence about font weight."""

    return FieldResult(
        Status.NOT_EVALUATED,
        WARNING_BOLD_EXPECTATION,
        None,
        None,
        crop,
        "Boldness is not recoverable from OCR text and was not evaluated.",
    )


def verify_type_size(*, crop: object | None = None) -> FieldResult:
    """Stay honest because text alone cannot establish physical type size."""

    return FieldResult(
        Status.NOT_EVALUATED,
        WARNING_TYPE_SIZE_EXPECTATION,
        None,
        None,
        crop,
        "Physical-size evidence is not available without image geometry and container "
        "dimensions; type size was not evaluated.",
    )
