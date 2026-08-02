from decimal import Decimal

from labelcheck.config import (
    EXACT_MATCH_CONFIDENCE,
    MISMATCH_CONFIDENCE,
    PROOF_ABV_TOLERANCE,
    PROOF_MULTIPLIER,
    WINE_FDA_JURISDICTION_MIN_ABV,
    abv_tolerance_for,
)
from labelcheck.models import FieldResult, Status
from labelcheck.normalize import (
    canonical_beverage_class,
    normalize_identity_text,
    parse_abv,
    parse_proof,
)


def verify(
    extracted: str | None,
    expected: str | None,
    *,
    beverage_class: str | None,
    crop: object | None = None,
) -> FieldResult:
    """Compare alcohol numerically and reject internally inconsistent stated proof."""

    if extracted is None or expected is None:
        return FieldResult(
            Status.NOT_EVALUATED,
            expected,
            extracted,
            None,
            crop,
            "Alcohol content was not located, so the check was not evaluated.",
        )
    if not normalize_identity_text(extracted) or not normalize_identity_text(expected):
        return FieldResult(
            Status.NOT_EVALUATED,
            expected,
            extracted,
            None,
            crop,
            "Alcohol content was not located, so the check was not evaluated.",
        )

    canonical_class = (
        canonical_beverage_class(beverage_class) if beverage_class is not None else None
    )
    extracted_abv: Decimal | None = None
    try:
        extracted_abv = parse_abv(extracted)
        expected_abv = parse_abv(expected)
        extracted_proof = parse_proof(extracted)
        application_proof = parse_proof(expected)
    except ValueError as error:
        jurisdiction_advisory = (
            _wine_jurisdiction_advisory(canonical_class, extracted_abv)
            if extracted_abv is not None
            else ""
        )
        return FieldResult(
            Status.REVIEW,
            expected,
            extracted,
            None,
            crop,
            f"Alcohol content could not be parsed unambiguously: {error}.{jurisdiction_advisory}",
        )

    jurisdiction_advisory = (
        _wine_jurisdiction_advisory(canonical_class, extracted_abv)
        if extracted_abv is not None
        else ""
    )

    if extracted_abv is None or expected_abv is None:
        return FieldResult(
            Status.REVIEW,
            expected,
            extracted,
            None,
            crop,
            "A numeric ABV was not available in both values; agent review is required."
            f"{jurisdiction_advisory}",
        )

    if application_proof is not None:
        proof_from_application_abv = expected_abv * PROOF_MULTIPLIER
        if abs(application_proof - proof_from_application_abv) > PROOF_ABV_TOLERANCE:
            return FieldResult(
                Status.REVIEW,
                expected,
                extracted,
                None,
                crop,
                f"Application proof {application_proof} is inconsistent with its ABV; "
                f"expected proof {proof_from_application_abv}.{jurisdiction_advisory}",
            )

    if canonical_class is None:
        return FieldResult(
            Status.REVIEW,
            expected,
            extracted,
            None,
            crop,
            "The beverage class could not be mapped to an ABV tolerance.",
        )

    if extracted_proof is not None:
        expected_proof = extracted_abv * PROOF_MULTIPLIER
        if abs(extracted_proof - expected_proof) > PROOF_ABV_TOLERANCE:
            return FieldResult(
                Status.FAIL,
                expected,
                extracted,
                MISMATCH_CONFIDENCE,
                crop,
                f"Stated proof {extracted_proof} is inconsistent with ABV; expected "
                f"proof {expected_proof}.{jurisdiction_advisory}",
            )

    tolerance = abv_tolerance_for(canonical_class, expected_abv)
    difference = abs(extracted_abv - expected_abv)
    if difference <= tolerance:
        return FieldResult(
            Status.PASS,
            expected,
            extracted,
            EXACT_MATCH_CONFIDENCE,
            crop,
            f"ABV differs by {difference} percentage points, within the CFR tolerance of "
            f"{tolerance} for this beverage class; any stated proof is consistent."
            f"{jurisdiction_advisory}",
        )
    return FieldResult(
        Status.FAIL,
        expected,
        extracted,
        MISMATCH_CONFIDENCE,
        crop,
        f"ABV differs by {difference} percentage points, beyond the CFR tolerance of "
        f"{tolerance} for this beverage class.{jurisdiction_advisory}",
    )


def _wine_jurisdiction_advisory(
    canonical_class: str | None,
    extracted_abv: Decimal,
) -> str:
    if canonical_class == "wine" and extracted_abv < WINE_FDA_JURISDICTION_MIN_ABV:
        return (
            f" Below {WINE_FDA_JURISDICTION_MIN_ABV}% ABV, the FAA Act and TTB wine "
            "labeling rules do not apply; FDA labeling governs under the 27 CFR 4.10 "
            "definition of wine."
        )
    return ""
