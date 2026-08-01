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
    """Preserve a human review band for materially close class/type wording."""

    if extracted is None or expected is None:
        return FieldResult(
            Status.NOT_EVALUATED,
            expected,
            extracted,
            None,
            crop,
            "Class/type text was not located, so the check was not evaluated.",
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
            "Class/type text was not located, so the check was not evaluated.",
        )

    confidence = float(token_sort_ratio(normalized_extracted, normalized_expected))
    if confidence >= FUZZY_PASS_THRESHOLD:
        status = Status.PASS
        detail = f"Class/type matched after normalization (similarity {confidence:.1f})."
    elif confidence >= FUZZY_REVIEW_THRESHOLD:
        status = Status.REVIEW
        detail = (
            "Class/type wording is close but not clearly the same; agent review is required."
        )
    else:
        status = Status.FAIL
        detail = (
            "Class/type wording does not match the application; agent review is required."
        )

    return FieldResult(status, expected, extracted, confidence, crop, detail)
