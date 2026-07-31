from labelcheck.config import (
    EXACT_MATCH_CONFIDENCE,
    FLUID_OUNCE_ROUNDING_TOLERANCE_ML,
    MISMATCH_CONFIDENCE,
    NET_CONTENTS_EXACT_TOLERANCE_ML,
)
from labelcheck.models import FieldResult, Status
from labelcheck.normalize import normalize_identity_text, parse_net_contents


def verify(
    extracted: str | None,
    expected: str | None,
    *,
    crop: object | None = None,
) -> FieldResult:
    """Compare canonical volume numbers so equivalent displayed units do not matter."""

    if extracted is None or expected is None:
        return FieldResult(
            Status.NOT_EVALUATED,
            expected,
            extracted,
            None,
            crop,
            "Net contents were not located, so the check was not evaluated.",
        )
    if not normalize_identity_text(extracted) or not normalize_identity_text(expected):
        return FieldResult(
            Status.NOT_EVALUATED,
            expected,
            extracted,
            None,
            crop,
            "Net contents were not located, so the check was not evaluated.",
        )

    try:
        extracted_ml, extracted_unit = parse_net_contents(extracted)
        expected_ml, expected_unit = parse_net_contents(expected)
    except ValueError as error:
        return FieldResult(
            Status.REVIEW,
            expected,
            extracted,
            None,
            crop,
            f"Net contents could not be parsed unambiguously: {error}.",
        )

    difference = abs(extracted_ml - expected_ml)
    tolerance = (
        FLUID_OUNCE_ROUNDING_TOLERANCE_ML
        if extracted_unit != expected_unit and "fl oz" in {extracted_unit, expected_unit}
        else NET_CONTENTS_EXACT_TOLERANCE_ML
    )
    if difference <= tolerance:
        return FieldResult(
            Status.PASS,
            expected,
            extracted,
            EXACT_MATCH_CONFIDENCE,
            crop,
            f"Net contents match after unit conversion ({extracted_ml} mL).",
        )
    return FieldResult(
        Status.FAIL,
        expected,
        extracted,
        MISMATCH_CONFIDENCE,
        crop,
        f"Net contents differ by {difference} mL after unit conversion.",
    )
