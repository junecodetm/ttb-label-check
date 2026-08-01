from __future__ import annotations

from collections.abc import Callable

from labelcheck import ocr, preprocess
from labelcheck.config import (
    GOVERNMENT_WARNING,
    GOVERNMENT_WARNING_PREFIX,
)
from labelcheck.extract import ExtractionState, FieldCandidate, extract_candidates
from labelcheck.models import ApplicationRecord, FieldResult, LabelReport, Status
from labelcheck.normalize import has_origin_value
from labelcheck.rules import alcohol, bottler, brand, class_type, net_contents, origin, warning


def _ambiguous_result(
    candidate: FieldCandidate,
    expected: str | None,
    field_label: str,
) -> FieldResult:
    alternatives = " | ".join(candidate.alternatives)
    return FieldResult(
        status=Status.REVIEW,
        expected=expected,
        extracted=alternatives or None,
        confidence=None,
        crop=candidate.crop,
        detail=f"Multiple {field_label} candidates were located; agent review is required.",
    )


def _evaluate_binary_rule(
    candidate: FieldCandidate,
    expected: str | None,
    field_label: str,
    rule: Callable[..., FieldResult],
) -> FieldResult:
    if candidate.state is ExtractionState.AMBIGUOUS:
        return _ambiguous_result(candidate, expected, field_label)
    return rule(candidate.value, expected, crop=candidate.crop)


def _evaluate_warning_rule(
    candidate: FieldCandidate,
    expected: str,
    field_label: str,
    rule: Callable[..., FieldResult],
) -> FieldResult:
    if candidate.state is ExtractionState.AMBIGUOUS:
        return _ambiguous_result(candidate, expected, field_label)
    return rule(candidate.value, crop=candidate.crop)


def verify(image_bytes: bytes, expected: ApplicationRecord) -> LabelReport:
    """Run one local OCR pass, then route evidence through every existing field rule."""

    if not isinstance(expected, ApplicationRecord):
        raise TypeError("expected must be an ApplicationRecord")

    # Both calls already raise this module's own typed errors: preprocess converts every
    # decode failure to ValueError, and ocr.recognize raises OcrError. Re-wrapping them
    # here would only rename an image problem into an OCR one.
    image = preprocess.preprocess_image(image_bytes)
    blocks = ocr.recognize(image)
    candidates = extract_candidates(blocks, image)

    results: dict[str, FieldResult] = {}
    results["brand_name"] = _evaluate_binary_rule(
        candidates["brand_name"], expected.brand_name, "brand-name", brand.verify
    )
    results["class_type"] = _evaluate_binary_rule(
        candidates["class_type"], expected.class_type, "class/type", class_type.verify
    )

    alcohol_candidate = candidates["alcohol_content"]
    if alcohol_candidate.state is ExtractionState.AMBIGUOUS:
        results["alcohol_content"] = _ambiguous_result(
            alcohol_candidate, expected.alcohol_content, "alcohol-content"
        )
    else:
        results["alcohol_content"] = alcohol.verify(
            alcohol_candidate.value,
            expected.alcohol_content,
            beverage_class=expected.class_type,
            crop=alcohol_candidate.crop,
        )

    results["net_contents"] = _evaluate_binary_rule(
        candidates["net_contents"],
        expected.net_contents,
        "net-contents",
        net_contents.verify,
    )
    results["bottler"] = _evaluate_binary_rule(
        candidates["bottler"], expected.bottler, "bottler", bottler.verify
    )
    origin_candidate = candidates["origin_country"]
    if origin_candidate.state is ExtractionState.AMBIGUOUS:
        origin_required = has_origin_value(expected.origin_country)
        if origin_required:
            results["origin_country"] = _ambiguous_result(
                origin_candidate, expected.origin_country, "country-of-origin"
            )
        else:
            results["origin_country"] = origin.verify(
                None,
                expected.origin_country,
                crop=origin_candidate.crop,
            )
    else:
        results["origin_country"] = origin.verify(
            origin_candidate.value,
            expected.origin_country,
            crop=origin_candidate.crop,
        )

    warning_candidate = candidates["government_warning"]
    results["government_warning"] = _evaluate_warning_rule(
        warning_candidate,
        GOVERNMENT_WARNING,
        "government-warning wording",
        warning.verify,
    )
    results["government_warning_prefix"] = _evaluate_warning_rule(
        warning_candidate,
        GOVERNMENT_WARNING_PREFIX,
        "government-warning prefix",
        warning.verify_prefix,
    )
    results["government_warning_bold"] = warning.verify_bold(crop=warning_candidate.crop)
    results["government_warning_type_size"] = warning.verify_type_size(crop=warning_candidate.crop)

    return LabelReport(results)
