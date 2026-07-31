from labelcheck.models import Status
from labelcheck.rules.net_contents import verify


def test_equivalent_liter_and_milliliter_values_pass() -> None:
    result = verify("750 mL", "0.75 L")

    assert result.status is Status.PASS


def test_rounded_fluid_ounce_equivalent_passes() -> None:
    result = verify("25.36 fl oz", "750 mL")

    assert result.status is Status.PASS


def test_different_numeric_net_contents_fail() -> None:
    result = verify("700 mL", "750 mL")

    assert result.status is Status.FAIL


def test_same_unit_values_do_not_use_fluid_ounce_rounding_tolerance() -> None:
    result = verify("750.04 mL", "750 mL")

    assert result.status is Status.FAIL


def test_same_unit_fluid_ounces_also_compare_exactly() -> None:
    result = verify("25.360 fl oz", "25.361 fl oz")

    assert result.status is Status.FAIL


def test_unparseable_net_contents_require_review() -> None:
    result = verify("one bottle", "750 mL")

    assert result.status is Status.REVIEW
    assert result.confidence is None


def test_missing_net_contents_are_not_evaluated() -> None:
    result = verify("", "750 mL")

    assert result.status is Status.NOT_EVALUATED


def test_net_contents_result_preserves_crop_and_raw_values() -> None:
    crop = object()

    result = verify("1 L", "1000 mL", crop=crop)

    assert result.expected == "1000 mL"
    assert result.extracted == "1 L"
    assert result.crop is crop
