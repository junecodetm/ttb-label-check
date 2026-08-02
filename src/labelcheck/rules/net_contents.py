from decimal import Decimal

from labelcheck.config import (
    EXACT_MATCH_CONFIDENCE,
    FLUID_OUNCE_ROUNDING_TOLERANCE_ML,
    MISMATCH_CONFIDENCE,
    NET_CONTENTS_EXACT_TOLERANCE_ML,
    STANDARD_OF_FILL_FL_OZ_TOLERANCE_ML,
    STANDARDS_OF_FILL_ML,
    WINE_LARGE_FORMAT_MIN_ML,
    WINE_LARGE_FORMAT_STEP_ML,
)
from labelcheck.models import FieldResult, Status
from labelcheck.normalize import (
    canonical_beverage_class,
    normalize_identity_text,
    parse_net_contents,
)


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


def verify_standard_of_fill(
    extracted: str | None,
    expected: str | None,
    *,
    beverage_class: str | None,
    crop: object | None = None,
) -> FieldResult:
    """Check the class-specific container-size rule separately from value matching."""

    if extracted is None or not normalize_identity_text(extracted):
        return FieldResult(
            Status.NOT_EVALUATED,
            expected,
            extracted,
            None,
            crop,
            "Net contents were not located, so the standards-of-fill check was not evaluated.",
        )

    canonical_class = (
        canonical_beverage_class(beverage_class) if beverage_class is not None else None
    )
    if canonical_class == "beer":
        return FieldResult(
            Status.NOT_EVALUATED,
            expected,
            extracted,
            None,
            crop,
            "This check does not apply because 27 CFR Part 7 sets no standards of fill "
            "for malt beverages.",
        )
    if canonical_class not in STANDARDS_OF_FILL_ML:
        return FieldResult(
            Status.REVIEW,
            expected,
            extracted,
            None,
            crop,
            "The beverage class could not be mapped to a standards-of-fill table.",
        )

    try:
        extracted_ml, extracted_unit = parse_net_contents(extracted)
    except ValueError as error:
        return FieldResult(
            Status.REVIEW,
            expected,
            extracted,
            None,
            crop,
            f"Net contents could not be parsed unambiguously for the standards-of-fill "
            f"check: {error}.",
        )

    authorized_size = _authorized_size(extracted_ml, extracted_unit, canonical_class)
    if authorized_size is not None:
        section = _cfr_section(canonical_class, authorized_size)
        return FieldResult(
            Status.PASS,
            expected,
            extracted,
            EXACT_MATCH_CONFIDENCE,
            crop,
            f"Container size resolves to the authorized {authorized_size} mL size under {section}.",
        )

    expected_ml: Decimal | None = None
    expected_authorized_size: Decimal | None = None
    if expected is not None and normalize_identity_text(expected):
        try:
            expected_ml, expected_unit = parse_net_contents(expected)
        except ValueError:
            pass
        else:
            expected_authorized_size = _authorized_size(
                expected_ml,
                expected_unit,
                canonical_class,
            )

    if (
        expected_ml is not None
        and expected_authorized_size is not None
        and expected_ml != extracted_ml
    ):
        section = _cfr_section(canonical_class, expected_authorized_size)
        return FieldResult(
            Status.REVIEW,
            expected,
            extracted,
            None,
            crop,
            f"The label read {extracted_ml} mL, which is not an authorized size, while "
            f"the application value resolves to the authorized {expected_ml} mL size "
            f"under {section}. This is probably an OCR misread; agent review is required.",
        )

    nearest_size = _nearest_authorized_size(extracted_ml, canonical_class)
    section = _cfr_section(canonical_class, nearest_size)
    return FieldResult(
        Status.FAIL,
        expected,
        extracted,
        MISMATCH_CONFIDENCE,
        crop,
        f"Container size {extracted_ml} mL is not authorized. The nearest authorized "
        f"size is {nearest_size} mL under {section}.",
    )


def _authorized_size(
    amount_ml: Decimal,
    source_unit: str,
    canonical_class: str,
) -> Decimal | None:
    standard_sizes = STANDARDS_OF_FILL_ML[canonical_class]
    if source_unit == "fl oz":
        nearest_size = _nearest_authorized_size(amount_ml, canonical_class)
        if abs(amount_ml - nearest_size) <= STANDARD_OF_FILL_FL_OZ_TOLERANCE_ML:
            return nearest_size
        return None
    if amount_ml in standard_sizes:
        return amount_ml
    if canonical_class == "wine" and _is_wine_large_format(amount_ml):
        return amount_ml
    return None


def _nearest_authorized_size(amount_ml: Decimal, canonical_class: str) -> Decimal:
    candidates = list(STANDARDS_OF_FILL_ML[canonical_class])
    if canonical_class == "wine":
        candidates.append(_nearest_wine_large_format_size(amount_ml))
    return min(candidates, key=lambda size: (abs(amount_ml - size), size))


def _nearest_wine_large_format_size(amount_ml: Decimal) -> Decimal:
    if amount_ml <= WINE_LARGE_FORMAT_MIN_ML:
        return WINE_LARGE_FORMAT_MIN_ML
    numerator, denominator = amount_ml.as_integer_ratio()
    minimum = int(WINE_LARGE_FORMAT_MIN_ML)
    step = int(WINE_LARGE_FORMAT_STEP_ML)
    steps_from_minimum = (numerator - minimum * denominator) // (step * denominator)
    lower_size = minimum + steps_from_minimum * step
    upper_size = lower_size + step
    lower_distance = numerator - lower_size * denominator
    upper_distance = upper_size * denominator - numerator
    return Decimal(lower_size if lower_distance <= upper_distance else upper_size)


def _is_wine_large_format(amount_ml: Decimal) -> bool:
    if amount_ml < WINE_LARGE_FORMAT_MIN_ML:
        return False
    numerator, denominator = amount_ml.as_integer_ratio()
    step = int(WINE_LARGE_FORMAT_STEP_ML)
    return numerator % (step * denominator) == 0


def _cfr_section(canonical_class: str, authorized_size: Decimal) -> str:
    if canonical_class == "distilled_spirits":
        return "27 CFR 5.203(a)"
    if _is_wine_large_format(authorized_size):
        return "27 CFR 4.72(b)"
    return "27 CFR 4.72(a)"
