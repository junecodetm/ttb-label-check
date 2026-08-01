from rapidfuzz.fuzz import token_sort_ratio

from labelcheck.config import EXACT_MATCH_CONFIDENCE, FUZZY_REVIEW_THRESHOLD
from labelcheck.models import FieldResult, Status
from labelcheck.normalize import normalize_bottler_text, normalize_compact_bottler_text


def verify(
    extracted: str | None,
    expected: str | None,
    *,
    crop: object | None = None,
) -> FieldResult:
    """Send non-exact but plausible bottler identities to an agent for judgment."""

    if extracted is None or expected is None:
        return FieldResult(
            Status.NOT_EVALUATED,
            expected,
            extracted,
            None,
            crop,
            "Bottler text was not located or provided, so the check was not evaluated.",
        )

    normalized_extracted = normalize_bottler_text(extracted)
    normalized_expected = normalize_bottler_text(expected)
    if not normalized_extracted or not normalized_expected:
        return FieldResult(
            Status.NOT_EVALUATED,
            expected,
            extracted,
            None,
            crop,
            "Bottler text was not located or provided, so the check was not evaluated.",
        )

    if normalize_compact_bottler_text(extracted) == normalize_compact_bottler_text(expected):
        return FieldResult(
            Status.PASS,
            expected,
            extracted,
            EXACT_MATCH_CONFIDENCE,
            crop,
            "Bottler matches after cosmetic normalization.",
        )

    confidence = float(token_sort_ratio(normalized_extracted, normalized_expected))
    one_value_extends_the_other = normalized_extracted.startswith(
        f"{normalized_expected} "
    ) or normalized_expected.startswith(f"{normalized_extracted} ")
    if one_value_extends_the_other or confidence >= FUZZY_REVIEW_THRESHOLD:
        return FieldResult(
            Status.REVIEW,
            expected,
            extracted,
            confidence,
            crop,
            "Bottler name or address is close but differs; compare the label crop with "
            "the application.",
        )
    return FieldResult(
        Status.FAIL,
        expected,
        extracted,
        confidence,
        crop,
        "Bottler name or address does not match the application; agent review is required.",
    )
