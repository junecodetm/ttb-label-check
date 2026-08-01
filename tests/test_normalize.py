from decimal import Decimal

import pytest

from labelcheck.config import FLUID_OUNCE_TO_ML, GOVERNMENT_WARNING
from labelcheck.normalize import (
    canonical_beverage_class,
    collapse_whitespace,
    normalize_bottler_text,
    normalize_compact_fuzzy_text,
    normalize_fuzzy_text,
    normalize_identity_text,
    normalize_number,
    normalize_origin_text,
    normalize_warning_text,
    parse_abv,
    parse_net_contents_ml,
    parse_proof,
    word_level_diff,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  STONE'S THROW  ", "stones throw"),
        ("STONE’S THROW", "stones throw"),
        ("Old-Tom/Reserve", "old tom reserve"),
        ("OLD_TOM.RESERVE", "old tom reserve"),
        ("Straße", "strasse"),
        ("Café", "café"),
        ("Acme & Sons", "acme sons"),
        ("\tOld\u00a0Tom\r\nReserve ", "old tom reserve"),
        ("...", ""),
    ],
)
def test_fuzzy_text_normalizes_cosmetic_variation(raw: str, expected: str) -> None:
    assert normalize_fuzzy_text(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Old Tom Distillery, LLC", "old tom distillery"),
        ("Old Tom Distillery Inc.", "old tom distillery"),
        ("Acme Co., L.L.C.", "acme"),
        ("Acme Corporation Limited", "acme"),
        ("Acme LLC Reserve", "acme llc reserve"),
        ("Limited Edition", "limited edition"),
        ("Incredible Spirits", "incredible spirits"),
        ("Company", "company"),
        ("Limited", "limited"),
    ],
)
def test_fuzzy_text_only_drops_trailing_legal_suffixes(raw: str, expected: str) -> None:
    assert normalize_fuzzy_text(raw) == expected


def test_fuzzy_text_normalization_is_idempotent() -> None:
    once = normalize_fuzzy_text("  STONE'S-THROW, LLC ")

    assert normalize_fuzzy_text(once) == once


def test_compact_fuzzy_text_removes_only_word_boundaries() -> None:
    assert normalize_compact_fuzzy_text("OLDTOMDISTILLERY") == normalize_compact_fuzzy_text(
        "OLD TOM DISTILLERY"
    )
    assert normalize_compact_fuzzy_text("Distillery Old Tom") != normalize_compact_fuzzy_text(
        "Old Tom Distillery"
    )


def test_identity_text_does_not_drop_words_that_look_like_legal_suffixes() -> None:
    assert normalize_identity_text("Limited, Inc.") == "limited inc"


@pytest.mark.parametrize(
    "raw",
    [
        "Bottled by Stone's Throw Distillery",
        "Produced and bottled by Stone's Throw Distillery",
        "Distilled and bottled by Stone's Throw Distillery",
        "Bottled for Stone's Throw Distillery",
    ],
)
def test_bottler_text_removes_configured_label_boilerplate(raw: str) -> None:
    assert normalize_bottler_text(raw) == "stones throw distillery"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Bottled by Acme Distillery, Denver, CO", "acme distillery denver co"),
        ("Bottled by Acme Distillery, LLC", "acme distillery llc"),
    ],
)
def test_bottler_text_preserves_address_and_legal_suffix_tokens(
    raw: str,
    expected: str,
) -> None:
    assert normalize_bottler_text(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("France", "france"),
        ("Product of FRANCE.", "france"),
        ("Made in Spain", "spain"),
        ("Produced in Italy", "italy"),
        ("Imported from Japan", "japan"),
    ],
)
def test_origin_text_removes_only_configured_label_boilerplate(raw: str, expected: str) -> None:
    assert normalize_origin_text(raw) == expected


@pytest.mark.parametrize("normalizer", [normalize_fuzzy_text, normalize_identity_text])
def test_text_normalizers_reject_missing_values(normalizer: object) -> None:
    with pytest.raises(TypeError):
        normalizer(None)  # type: ignore[operator]


def test_whitespace_collapses_ascii_and_unicode_separators() -> None:
    assert collapse_whitespace("\t A\u00a0B \r\n C ") == "A B C"


@pytest.mark.parametrize(
    ("artifact", "expanded"),
    [
        ("oﬀice", "office"),
        ("ﬁnal", "final"),
        ("ﬂask", "flask"),
        ("eﬃcient", "efficient"),
        ("waﬄe", "waffle"),
    ],
)
def test_warning_normalization_expands_known_ocr_ligatures(artifact: str, expanded: str) -> None:
    assert normalize_warning_text(artifact) == expanded


def test_warning_normalization_repairs_only_contextual_l_one_i_confusions() -> None:
    warning_with_artifacts = (
        GOVERNMENT_WARNING.replace("WARNING", "WARN1NG")
        .replace("alcoholic", "alcoho1ic")
        .replace("ability", "abiIity")
        .replace("(1)", "(I)")
    )

    assert normalize_warning_text(warning_with_artifacts) == GOVERNMENT_WARNING


def test_warning_normalization_repairs_line_break_hyphenation() -> None:
    wrapped = GOVERNMENT_WARNING.replace("alcoholic", "alco-\n  holic")

    assert normalize_warning_text(wrapped) == GOVERNMENT_WARNING


def test_warning_normalization_does_not_remove_an_inline_hyphen() -> None:
    altered = GOVERNMENT_WARNING.replace("alcoholic", "alco-holic")

    assert normalize_warning_text(altered) != GOVERNMENT_WARNING
    assert "alco-holic" in normalize_warning_text(altered)


def test_warning_normalization_does_not_join_words_split_without_a_hyphen() -> None:
    altered = GOVERNMENT_WARNING.replace("alcoholic", "alco\nholic")

    assert "alco holic" in normalize_warning_text(altered)
    assert normalize_warning_text(altered) != GOVERNMENT_WARNING


def test_warning_normalization_preserves_case_and_unapproved_unicode() -> None:
    assert normalize_warning_text("Government Warning:") == "Government Warning:"
    assert normalize_warning_text("ＧOVERNMENT WARNING:") != "GOVERNMENT WARNING:"
    assert normalize_warning_text("GOVERNMENT\u200b WARNING:") != "GOVERNMENT WARNING:"


def test_warning_normalization_is_idempotent() -> None:
    once = normalize_warning_text("WARN1NG:  alco-\n holic")

    assert normalize_warning_text(once) == once


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("45", Decimal("45")),
        ("45.0", Decimal("45.0")),
        (".75", Decimal("0.75")),
        ("0.75", Decimal("0.75")),
        ("1,000", Decimal("1000")),
        ("1,000.50", Decimal("1000.50")),
    ],
)
def test_number_normalization_uses_exact_decimals(raw: str, expected: Decimal) -> None:
    assert normalize_number(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ["", "-1", "+1", "1e3", "NaN", "Inf", "45..5", "1,00", "0,75", "１２", "1 2"],
)
def test_number_normalization_rejects_malformed_or_ambiguous_values(raw: str) -> None:
    with pytest.raises(ValueError):
        normalize_number(raw)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("45% Alc./Vol. (90 Proof)", Decimal("45")),
        ("45.5 % ABV", Decimal("45.5")),
        ("Alcohol by volume 12%", Decimal("12")),
        ("750 mL; 40% alcohol by volume", Decimal("40")),
    ],
)
def test_abv_parser_anchors_the_number_to_an_abv_marker(raw: str, expected: Decimal) -> None:
    assert parse_abv(raw) == expected


def test_abv_parser_returns_none_when_no_abv_is_stated() -> None:
    assert parse_abv("90 Proof") is None
    assert parse_abv("100% agave") is None
    assert parse_abv("45%") is None


@pytest.mark.parametrize(
    "raw",
    [
        "101% ABV",
        "40% ABV and 45% ABV",
        "-45% ABV",
        "+45% ABV",
        "45..5% ABV",
        "1,00% ABV",
        "45% Alc/Volcano",
        "ABV 45%xyz",
    ],
)
def test_abv_parser_rejects_out_of_range_or_ambiguous_values(raw: str) -> None:
    with pytest.raises(ValueError):
        parse_abv(raw)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("45% Alc./Vol. (90 Proof)", Decimal("90")),
        ("PROOF 90", Decimal("90")),
        ("90.5 proof", Decimal("90.5")),
    ],
)
def test_proof_parser_anchors_the_number_to_proof(raw: str, expected: Decimal) -> None:
    assert parse_proof(raw) == expected


def test_proof_parser_returns_none_when_no_proof_is_stated() -> None:
    assert parse_proof("45% ABV") is None


@pytest.mark.parametrize(
    "raw",
    [
        "201 Proof",
        "80 Proof / 90 Proof",
        "-90 Proof",
        "+90 Proof",
        "90..5 Proof",
        "1,00 Proof",
        "eighty Proof",
        "Proof 90xyz",
        "Proof 90e3",
    ],
)
def test_proof_parser_rejects_out_of_range_or_ambiguous_values(raw: str) -> None:
    with pytest.raises(ValueError):
        parse_proof(raw)


@pytest.mark.parametrize(
    ("raw", "expected_ml"),
    [
        ("750 mL", Decimal("750")),
        ("0.75 L", Decimal("750")),
        ("1.5L", Decimal("1500")),
        ("1,000 milliliters", Decimal("1000")),
        ("1 litre", Decimal("1000")),
        ("12 fl. oz.", Decimal("12") * FLUID_OUNCE_TO_ML),
        ("12 FL OZ", Decimal("12") * FLUID_OUNCE_TO_ML),
    ],
)
def test_net_contents_parser_normalizes_supported_units(raw: str, expected_ml: Decimal) -> None:
    assert parse_net_contents_ml(raw) == expected_ml


@pytest.mark.parametrize(
    "raw",
    ["", "750", "750 oz", "750 mg", "-750 mL", "0,75 L", "75O mL", "750 mL / 1 L"],
)
def test_net_contents_parser_rejects_missing_malformed_or_ambiguous_units(raw: str) -> None:
    with pytest.raises(ValueError):
        parse_net_contents_ml(raw)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("beer", "beer"),
        ("India Pale Ale", "beer"),
        ("Malt Beverage", "beer"),
        ("Barley Wine", "beer"),
        ("Cabernet Sauvignon Wine", "wine"),
        ("Kentucky Straight Bourbon Whiskey", "distilled_spirits"),
        ("Vodka", "distilled_spirits"),
        ("unknown beverage", None),
    ],
)
def test_beverage_classes_are_canonicalized_for_tolerance_lookup(
    raw: str, expected: str | None
) -> None:
    assert canonical_beverage_class(raw) == expected


def test_word_diff_reports_insertions_deletions_and_replacements() -> None:
    assert word_level_diff("may cause health problems", "may cause serious health problems") == (
        "unexpected extracted [serious]"
    )
    assert word_level_diff("may cause health problems", "may cause problems") == (
        "missing expected [health]"
    )
    assert word_level_diff("may cause health problems", "may create health problems") == (
        "replace expected [cause] with extracted [create]"
    )


def test_word_diff_is_empty_for_identical_text() -> None:
    assert word_level_diff(GOVERNMENT_WARNING, GOVERNMENT_WARNING) == ""
