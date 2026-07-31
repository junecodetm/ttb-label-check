from labelcheck.config import EXACT_MATCH_CONFIDENCE, MISMATCH_CONFIDENCE
from labelcheck.models import FieldResult, Status
from labelcheck.normalize import normalize_origin_text


def verify(
    extracted: str | None,
    expected: str | None,
    *,
    crop: object | None = None,
) -> FieldResult:
    """Evaluate origin only when the application record identifies an import."""

    normalized_expected = normalize_origin_text(expected) if expected is not None else ""
    if not normalized_expected:
        return FieldResult(
            Status.NOT_EVALUATED,
            expected,
            extracted,
            None,
            crop,
            "Country of origin does not apply to this domestic application.",
        )

    normalized_extracted = normalize_origin_text(extracted) if extracted is not None else ""
    if not normalized_extracted:
        return FieldResult(
            Status.NOT_EVALUATED,
            expected,
            extracted,
            None,
            crop,
            "Required import origin text was not located, so the check was not evaluated.",
        )

    if normalized_extracted == normalized_expected:
        return FieldResult(
            Status.PASS,
            expected,
            extracted,
            EXACT_MATCH_CONFIDENCE,
            crop,
            "Country of origin matches after cosmetic normalization.",
        )
    return FieldResult(
        Status.FAIL,
        expected,
        extracted,
        MISMATCH_CONFIDENCE,
        crop,
        "Country of origin does not match the import application.",
    )
