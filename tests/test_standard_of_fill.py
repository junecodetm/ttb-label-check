from labelcheck.config import EXACT_MATCH_CONFIDENCE, MISMATCH_CONFIDENCE
from labelcheck.models import Status
from labelcheck.rules import net_contents


def test_700_ml_spirits_is_authorized() -> None:
    result = net_contents.verify_standard_of_fill(
        "700 mL",
        "700 mL",
        beverage_class="distilled spirits",
    )

    assert result.status is Status.PASS
    assert result.confidence == EXACT_MATCH_CONFIDENCE
    assert "5.203(a)" in result.detail


def test_700_ml_wine_is_authorized() -> None:
    result = net_contents.verify_standard_of_fill(
        "700 mL",
        "700 mL",
        beverage_class="wine",
    )

    assert result.status is Status.PASS
    assert "4.72(a)" in result.detail


def test_701_ml_with_authorized_application_value_requires_review() -> None:
    result = net_contents.verify_standard_of_fill(
        "701 mL",
        "750 mL",
        beverage_class="spirits",
    )

    assert result.status is Status.REVIEW
    assert result.confidence is None
    assert "OCR" in result.detail
    assert "701" in result.detail
    assert "750" in result.detail


def test_701_ml_confirmed_by_application_fails() -> None:
    result = net_contents.verify_standard_of_fill(
        "701 mL",
        "701 mL",
        beverage_class="spirits",
    )

    assert result.status is Status.FAIL
    assert result.confidence == MISMATCH_CONFIDENCE
    assert "700" in result.detail
    assert "5.203(a)" in result.detail


def test_4_l_wine_passes_large_format_rule() -> None:
    result = net_contents.verify_standard_of_fill(
        "4 L",
        "4 L",
        beverage_class="wine",
    )

    assert result.status is Status.PASS
    assert "4.72(b)" in result.detail


def test_6_l_wine_passes_large_format_rule() -> None:
    result = net_contents.verify_standard_of_fill(
        "6 L",
        "6 L",
        beverage_class="wine",
    )

    assert result.status is Status.PASS
    assert "4.72(b)" in result.detail


def test_5_5_l_wine_fails() -> None:
    result = net_contents.verify_standard_of_fill(
        "5.5 L",
        "5.5 L",
        beverage_class="wine",
    )

    assert result.status is Status.FAIL
    assert "5000" in result.detail
    assert "4.72(b)" in result.detail


def test_large_whole_liter_wine_size_is_authorized() -> None:
    result = net_contents.verify_standard_of_fill(
        "18 L",
        "18 L",
        beverage_class="wine",
    )

    assert result.status is Status.PASS
    assert "4.72(b)" in result.detail


def test_fl_oz_stated_750_ml_equivalent_passes() -> None:
    result = net_contents.verify_standard_of_fill(
        "25.4 fl oz",
        "750 mL",
        beverage_class="spirits",
    )

    assert result.status is Status.PASS


def test_malt_beverage_is_not_evaluated() -> None:
    result = net_contents.verify_standard_of_fill(
        "12 fl oz",
        "12 fl oz",
        beverage_class="malt beverage",
    )

    assert result.status is Status.NOT_EVALUATED
    assert "Part 7" in result.detail


def test_unknown_class_requires_review() -> None:
    result = net_contents.verify_standard_of_fill(
        "700 mL",
        "700 mL",
        beverage_class="experimental beverage",
    )

    assert result.status is Status.REVIEW
    assert "beverage class" in result.detail.lower()


def test_missing_value_not_evaluated() -> None:
    missing = net_contents.verify_standard_of_fill(
        None,
        "750 mL",
        beverage_class="spirits",
    )
    blank = net_contents.verify_standard_of_fill(
        "   ",
        "750 mL",
        beverage_class="spirits",
    )

    assert missing.status is Status.NOT_EVALUATED
    assert blank.status is Status.NOT_EVALUATED


def test_unparseable_value_requires_review() -> None:
    result = net_contents.verify_standard_of_fill(
        "one bottle",
        "750 mL",
        beverage_class="spirits",
    )

    assert result.status is Status.REVIEW
    assert result.confidence is None


def test_result_preserves_crop_and_raw_values() -> None:
    crop = object()

    result = net_contents.verify_standard_of_fill(
        "701 mL",
        "750 mL",
        beverage_class="spirits",
        crop=crop,
    )

    assert result.expected == "750 mL"
    assert result.extracted == "701 mL"
    assert result.crop is crop
