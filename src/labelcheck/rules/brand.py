from rapidfuzz.fuzz import token_sort_ratio

from labelcheck.config import FUZZY_PASS_THRESHOLD, FUZZY_REVIEW_THRESHOLD
from labelcheck.models import FieldResult, Status
from labelcheck.normalize import normalize_fuzzy_text


def verify(
    extracted: str | None,
    expected: str | None,
    *,
    crop: object | None = None,
) -> FieldResult:
    """Escalate human-plausible brand variants instead of auto-rejecting them."""

    if extracted is None or expected is None:
        return FieldResult(
            Status.NOT_EVALUATED,
            expected,
            extracted,
            None,
            crop,
            "Brand text was not located, so the check was not evaluated.",
        )

    normalized_extracted = normalize_fuzzy_text(extracted)
    normalized_expected = normalize_fuzzy_text(expected)
    if not normalized_extracted or not normalized_expected:
        return FieldResult(
            Status.NOT_EVALUATED,
            expected,
            extracted,
            None,
            crop,
            "Brand text was not located, so the check was not evaluated.",
        )

    confidence = float(token_sort_ratio(normalized_extracted, normalized_expected))
    if confidence >= FUZZY_PASS_THRESHOLD:
        status = Status.PASS
        detail = f"Brand matched after normalization (similarity {confidence:.1f})."
    elif confidence >= FUZZY_REVIEW_THRESHOLD:
        status = Status.REVIEW
        detail = f"Brand similarity {confidence:.1f} is ambiguous and needs agent review."
    else:
        status = Status.FAIL
        detail = f"Brand similarity {confidence:.1f} is below the accepted bands."

    return FieldResult(status, expected, extracted, confidence, crop, detail)
