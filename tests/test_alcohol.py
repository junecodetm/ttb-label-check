import time
from decimal import Decimal

import pytest

from labelcheck.models import Status
from labelcheck.normalize import parse_abv
from labelcheck.rules.alcohol import verify


def test_equal_abv_without_optional_proof_passes() -> None:
    result = verify("13.5% ABV", "13.5% Alc./Vol.", beverage_class="wine")

    assert result.status is Status.PASS


def test_decimal_abv_and_consistent_proof_pass() -> None:
    result = verify("45.5% ABV (91 Proof)", "45.5% ABV", beverage_class="bourbon whiskey")

    assert result.status is Status.PASS


def test_whole_number_proof_rounding_within_abv_tolerance_passes() -> None:
    result = verify(
        "40.3% Alc./Vol. (81 Proof)",
        "40.3% Alc./Vol.",
        beverage_class="distilled spirits",
    )

    assert result.status is Status.PASS


def test_spirits_abv_within_the_cfr_tolerance_passes() -> None:
    # 27 CFR 5.65 allows plus or minus 0.3 percentage points.
    result = verify("44.8% ABV", "45% ABV", beverage_class="distilled spirits")

    assert result.status is Status.PASS


def test_spirits_abv_beyond_the_cfr_tolerance_fails() -> None:
    result = verify("44.5% ABV", "45% ABV", beverage_class="distilled spirits")

    assert result.status is Status.FAIL
    assert "0.3" in result.detail


def test_wine_at_or_below_14_percent_gets_the_wider_band() -> None:
    # 27 CFR 4.36(b): 1.5 points at or below 14% ABV, 1.0 above it. A 1.2-point
    # deviation therefore passes for a 13% wine and fails for a 15% one — the
    # banding is the whole point, so both sides are asserted.
    result = verify("11.8% ABV", "13% ABV", beverage_class="wine")

    assert result.status is Status.PASS


def test_wine_above_14_percent_gets_the_narrower_band() -> None:
    result = verify("13.8% ABV", "15% ABV", beverage_class="wine")

    assert result.status is Status.FAIL


def test_malt_beverage_below_half_a_percent_gets_no_tolerance() -> None:
    # 27 CFR 7.65 extends its 0.3-point tolerance only to malt beverages at
    # 0.5% ABV or more, which is where "non-alcoholic" claims sit.
    result = verify("0.3% ABV", "0.4% ABV", beverage_class="beer")

    assert result.status is Status.FAIL


def test_malt_beverage_above_half_a_percent_gets_the_tolerance() -> None:
    result = verify("5.1% ABV", "5% ABV", beverage_class="beer")

    assert result.status is Status.PASS


def test_inconsistent_stated_proof_fails_even_when_abv_matches() -> None:
    result = verify("45% ABV (80 Proof)", "45% ABV", beverage_class="distilled spirits")

    assert result.status is Status.FAIL
    assert "90" in result.detail


def test_invalid_alcohol_text_requires_review_instead_of_fake_pass() -> None:
    result = verify("forty-five percent", "45% ABV", beverage_class="distilled spirits")

    assert result.status is Status.REVIEW
    assert result.confidence is None


def test_unrelated_or_malformed_percent_cannot_pass_as_abv() -> None:
    unrelated = verify("45% agave", "45% ABV", beverage_class="tequila")
    negative = verify("-45% ABV", "45% ABV", beverage_class="wine")

    assert unrelated.status is Status.REVIEW
    assert negative.status is Status.REVIEW


def test_malformed_stated_proof_requires_review() -> None:
    result = verify("45% ABV (eighty Proof)", "45% ABV", beverage_class="spirits")

    assert result.status is Status.REVIEW
    assert "proof" in result.detail.lower()


def test_marker_prefixes_and_trailing_token_junk_cannot_pass() -> None:
    malformed_proof = verify("45% ABV (Proof 90xyz)", "45% ABV", beverage_class="distilled spirits")
    malformed_abv = verify("45% Alc/Volcano", "45% Alc./Vol.", beverage_class="distilled spirits")

    assert malformed_proof.status is Status.REVIEW
    assert malformed_abv.status is Status.REVIEW


def test_inconsistent_proof_in_application_record_cannot_produce_pass() -> None:
    result = verify(
        "45% ABV (90 Proof)",
        "45% ABV (80 Proof)",
        beverage_class="distilled spirits",
    )

    assert result.status is Status.REVIEW
    assert "application" in result.detail.lower()


def test_missing_alcohol_text_is_not_evaluated() -> None:
    result = verify(None, "45% ABV", beverage_class="distilled spirits")

    assert result.status is Status.NOT_EVALUATED


def test_unknown_beverage_class_requires_review() -> None:
    result = verify("45% ABV", "45% ABV", beverage_class="experimental beverage")

    assert result.status is Status.REVIEW
    assert "beverage class" in result.detail.lower()


def test_alcohol_result_preserves_raw_values_and_crop() -> None:
    crop = object()

    result = verify("45% ABV", "45% Alc./Vol.", beverage_class="spirits", crop=crop)

    assert result.expected == "45% Alc./Vol."
    assert result.extracted == "45% ABV"
    assert result.crop is crop


def test_adversarial_alcohol_text_cannot_stall_the_parser() -> None:
    """A manifest cell must not be able to burn a worker thread.

    An earlier marker pattern chained optional groups around \\s*, so a failed match
    backtracked super-linearly: "ALC" plus 2000 spaces took 9.8 seconds, and 300 such
    rows would have stalled a batch for the better part of an hour.
    """

    hostile = "ALC" + " " * 4000 + "X"

    started = time.perf_counter()
    try:
        parse_abv(hostile)
    except ValueError:
        pass  # Rejecting it is fine. Taking ten seconds to reject it is not.
    assert time.perf_counter() - started < 1.0


@pytest.mark.parametrize(
    "line",
    [
        "GRAPE JUICE 100% BY VOLUME",
        "SERVING FACTS 5 fl oz 12% BY VOLUME",
        "CONTAINS 30% BY VOLUME FRUIT JUICE",
    ],
)
def test_percent_by_volume_alone_is_not_an_alcohol_statement(line: str) -> None:
    """Juice-content and nutrition panels state percentages that are not alcohol."""

    assert parse_abv(line) is None


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("45% Alc./Vol. (90 Proof)", Decimal("45")),
        ("Alcohol Content 40% by Vol", Decimal("40")),
        ("Alcohol Content40% by Vol", Decimal("40")),
        ("40% ABV", Decimal("40")),
        ("5.5% alcohol by volume", Decimal("5.5")),
    ],
)
def test_real_label_alcohol_wordings_are_read(line: str, expected: Decimal) -> None:
    assert parse_abv(line) == expected
