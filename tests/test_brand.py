from labelcheck.models import Status
from labelcheck.rules.brand import verify


def test_exact_brand_match_passes_with_full_result_payload() -> None:
    crop = object()

    result = verify("Old Tom Distillery", "Old Tom Distillery", crop=crop)

    assert result.status is Status.PASS
    assert result.expected == "Old Tom Distillery"
    assert result.extracted == "Old Tom Distillery"
    assert result.confidence == 100.0
    assert result.crop is crop
    assert result.detail


def test_brand_cosmetic_variation_and_legal_suffixes_pass() -> None:
    result = verify("THE STONE'S THROW, LLC", "The Stones Throw Inc.")

    assert result.status is Status.PASS


def test_brand_token_order_variation_passes() -> None:
    result = verify("Distillery Old Tom", "Old Tom Distillery")

    assert result.status is Status.PASS


def test_brand_that_is_only_a_suffix_like_word_still_compares() -> None:
    result = verify("Company", "Company")

    assert result.status is Status.PASS


def test_brand_near_match_enters_the_review_band() -> None:
    result = verify("Old Thyme Distillery", "Old Tom Distillery")

    assert result.status is Status.REVIEW
    assert 70.0 <= result.confidence < 90.0


def test_brand_clear_mismatch_fails() -> None:
    result = verify("Stone Creek", "Old Tom Distillery")

    assert result.status is Status.FAIL


def test_missing_brand_is_not_evaluated_never_passed() -> None:
    result = verify(None, "Old Tom Distillery")

    assert result.status is Status.NOT_EVALUATED
    assert result.confidence is None
    assert "not located" in result.detail.lower()
