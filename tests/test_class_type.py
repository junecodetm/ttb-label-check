from labelcheck.models import Status
from labelcheck.rules.class_type import verify


def test_exact_class_type_match_passes() -> None:
    result = verify("Kentucky Straight Bourbon Whiskey", "Kentucky Straight Bourbon Whiskey")

    assert result.status is Status.PASS


def test_class_type_cosmetic_and_token_order_variation_passes() -> None:
    result = verify("Whiskey, Bourbon - Kentucky Straight", "Kentucky Straight Bourbon Whiskey")

    assert result.status is Status.PASS


def test_class_type_near_match_enters_the_review_band() -> None:
    result = verify("Kentucky Bourbon Whiskey", "Kentucky Straight Bourbon Whiskey")

    assert result.status is Status.REVIEW
    assert 70.0 <= result.confidence < 90.0


def test_class_type_clear_mismatch_fails() -> None:
    result = verify("Cabernet Sauvignon", "Kentucky Straight Bourbon Whiskey")

    assert result.status is Status.FAIL


def test_missing_class_type_is_not_evaluated() -> None:
    result = verify("", "Kentucky Straight Bourbon Whiskey")

    assert result.status is Status.NOT_EVALUATED
    assert result.confidence is None
