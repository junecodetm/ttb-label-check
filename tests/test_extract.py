import numpy as np
import pytest

from labelcheck.config import GOVERNMENT_WARNING
from labelcheck.extract import FIELD_NAMES, ExtractionState, extract_candidates
from labelcheck.models import TextBlock
from labelcheck.normalize import normalize_bottler_text, normalize_warning_text


def _block(
    text: str,
    left: float,
    top: float,
    right: float,
    bottom: float,
    confidence: float = 0.97,
) -> TextBlock:
    return TextBlock(
        text=text,
        bbox=((left, top), (right, top), (right, bottom), (left, bottom)),
        confidence=confidence,
    )


def test_layout_and_text_patterns_extract_each_candidate_with_a_crop() -> None:
    words = GOVERNMENT_WARNING.split()
    warning_blocks = [
        _block(" ".join(words[:17]), 35, 210, 760, 228),
        _block(" ".join(words[17:34]), 35, 234, 770, 252),
        _block(" ".join(words[34:]), 35, 258, 720, 276),
    ]
    blocks = [
        _block("750 mL", 320, 122, 455, 144),
        warning_blocks[2],
        _block("EST. 1890", 650, 12, 770, 27),
        _block("OLD TOM DISTILLERY", 165, 35, 630, 78),
        _block("Product of Scotland", 35, 174, 260, 193),
        warning_blocks[0],
        _block("45% Alc./Vol. (90 Proof)", 240, 91, 565, 115),
        _block("Bottled by Old Tom Distillery, Bardstown, Kentucky", 35, 151, 620, 170),
        warning_blocks[1],
        _block("Kentucky Straight Bourbon Whiskey", 180, 79, 610, 99),
    ]
    image = np.full((300, 800, 3), 255, dtype=np.uint8)

    candidates = extract_candidates(blocks, image)

    assert candidates["brand_name"].value == "OLD TOM DISTILLERY"
    assert candidates["class_type"].value == "Kentucky Straight Bourbon Whiskey"
    assert candidates["alcohol_content"].value == "45% Alc./Vol. (90 Proof)"
    assert candidates["net_contents"].value == "750 mL"
    assert candidates["bottler"].value == "Bottled by Old Tom Distillery, Bardstown, Kentucky"
    assert candidates["origin_country"].value == "Product of Scotland"
    assert (
        normalize_warning_text(candidates["government_warning"].value or "") == GOVERNMENT_WARNING
    )
    assert all(candidate.state is ExtractionState.FOUND for candidate in candidates.values())
    assert all(candidate.crop.startswith(b"\x89PNG\r\n\x1a\n") for candidate in candidates.values())


def test_explicit_labels_outrank_type_size_and_are_removed_from_values() -> None:
    blocks = [
        _block("Decorative Anniversary Release", 20, 10, 760, 70),
        _block("Brand Name: OLD TOM DISTILLERY", 30, 85, 520, 110),
        _block("Class/Type: Kentucky Straight Bourbon Whiskey", 30, 118, 650, 140),
        _block("Alcohol Content: 45% Alc./Vol. (90 Proof)", 30, 148, 620, 170),
        _block("Net Contents: 750 mL", 30, 178, 300, 200),
        _block(
            "Bottler: Bottled by Old Tom Distillery, Bardstown, Kentucky",
            30,
            208,
            760,
            230,
        ),
        _block("Country of Origin: Scotland", 30, 238, 390, 260),
    ]
    image = np.full((300, 800, 3), 255, dtype=np.uint8)

    candidates = extract_candidates(blocks, image)

    assert candidates["brand_name"].value == "OLD TOM DISTILLERY"
    assert candidates["class_type"].value == "Kentucky Straight Bourbon Whiskey"
    assert candidates["alcohol_content"].value == "45% Alc./Vol. (90 Proof)"
    assert candidates["net_contents"].value == "750 mL"
    assert candidates["bottler"].value == "Bottled by Old Tom Distillery, Bardstown, Kentucky"
    assert candidates["origin_country"].value == "Scotland"


def test_multiple_numeric_candidates_are_ambiguous_instead_of_arbitrarily_selected() -> None:
    blocks = [
        _block("45% Alc./Vol. (90 Proof)", 20, 20, 350, 45),
        _block("40% Alc./Vol. (80 Proof)", 20, 55, 350, 80),
        _block("750 mL", 20, 90, 140, 115),
        _block("1 L", 20, 125, 100, 150),
    ]
    image = np.full((180, 400, 3), 255, dtype=np.uint8)

    candidates = extract_candidates(blocks, image)

    assert candidates["alcohol_content"].state is ExtractionState.AMBIGUOUS
    assert candidates["alcohol_content"].value is None
    assert set(candidates["alcohol_content"].alternatives) == {
        "45% Alc./Vol. (90 Proof)",
        "40% Alc./Vol. (80 Proof)",
    }
    assert candidates["net_contents"].state is ExtractionState.AMBIGUOUS
    assert candidates["net_contents"].value is None
    assert candidates["alcohol_content"].crop
    assert candidates["net_contents"].crop


def test_multiple_warning_candidates_are_ambiguous_even_when_the_first_is_exact() -> None:
    altered_warning = GOVERNMENT_WARNING.replace("health problems", "serious health problems")
    blocks = [
        _block(GOVERNMENT_WARNING, 20, 20, 780, 55),
        _block(altered_warning, 20, 100, 780, 135),
    ]
    image = np.full((170, 800, 3), 255, dtype=np.uint8)

    candidate = extract_candidates(blocks, image)["government_warning"]

    assert candidate.state is ExtractionState.AMBIGUOUS
    assert candidate.value is None
    assert set(candidate.alternatives) == {GOVERNMENT_WARNING, altered_warning}
    assert candidate.crop


def test_bottler_signal_on_its_own_line_collects_contiguous_address_lines() -> None:
    blocks = [
        _block("Bottled by", 20, 20, 150, 42),
        _block("Old Tom Distillery", 20, 47, 260, 69),
        _block("Bardstown, Kentucky", 20, 74, 280, 96),
    ]
    image = np.full((130, 400, 3), 255, dtype=np.uint8)

    candidate = extract_candidates(blocks, image)["bottler"]

    assert candidate.state is ExtractionState.FOUND
    assert candidate.value == "Bottled by\nOld Tom Distillery\nBardstown, Kentucky"
    assert len(candidate.blocks) == 3
    assert candidate.crop


@pytest.mark.parametrize(
    "phrase",
    [
        "packaged by",
        "brewed by",
        "distilled by",
        "distilled and bottled by",
        "produced and bottled by",
        "produced by",
        "blended and bottled by",
        "blended by",
        "imported by",
        "vinted by",
        "vinted and bottled by",
        "canned by",
        "brewed and bottled by",
        "brewed and canned by",
        "cellared and bottled by",
        "made by",
        "prepared by",
    ],
)
def test_common_bottler_phrases_are_detected_and_fully_removed(phrase: str) -> None:
    blocks = [_block(f"{phrase} Acme Cellars", 20, 20, 300, 42)]
    image = np.full((80, 340, 3), 255, dtype=np.uint8)

    candidate = extract_candidates(blocks, image)["bottler"]

    assert candidate.state is ExtractionState.FOUND
    assert normalize_bottler_text(candidate.value or "") == "acme cellars"


@pytest.mark.parametrize("prefix", ["PRODUCT OF", "PRODUCED IN"])
def test_wrapped_origin_statement_collects_the_country_continuation(prefix: str) -> None:
    blocks = [
        _block(prefix, 20, 20, 180, 42),
        _block("United Kingdom", 20, 47, 220, 69),
    ]
    image = np.full((100, 300, 3), 255, dtype=np.uint8)

    candidate = extract_candidates(blocks, image)["origin_country"]

    assert candidate.state is ExtractionState.FOUND
    assert candidate.value == f"{prefix}\nUnited Kingdom"
    assert len(candidate.blocks) == 2
    assert candidate.crop


def test_adjacent_centered_brand_lines_are_one_candidate() -> None:
    blocks = [
        _block("OLD TOM", 125, 20, 275, 60),
        _block("DISTILLERY", 90, 66, 310, 106),
        _block("Kentucky Straight Bourbon Whiskey", 55, 125, 345, 150),
        _block("45% Alc./Vol.", 135, 165, 265, 188),
        _block("750 mL", 165, 200, 235, 222),
    ]
    image = np.full((250, 400, 3), 255, dtype=np.uint8)

    candidate = extract_candidates(blocks, image)["brand_name"]

    assert candidate.state is ExtractionState.FOUND
    assert candidate.value == "OLD TOM DISTILLERY"
    assert len(candidate.blocks) == 2
    assert candidate.bbox[0] == (90.0, 20.0)
    assert candidate.bbox[2] == (310.0, 106.0)
    assert candidate.crop


def test_separated_large_text_runs_remain_ambiguous_brand_candidates() -> None:
    blocks = [
        _block("OLD TOM", 125, 20, 275, 60),
        _block("ANNIVERSARY RELEASE", 60, 145, 340, 185),
    ]
    image = np.full((220, 400, 3), 255, dtype=np.uint8)

    candidate = extract_candidates(blocks, image)["brand_name"]

    assert candidate.state is ExtractionState.AMBIGUOUS
    assert set(candidate.alternatives) == {"OLD TOM", "ANNIVERSARY RELEASE"}


def test_missing_and_malformed_blocks_return_all_fields_with_fallback_crops() -> None:
    blocks = [
        TextBlock("unusable", (), 0.9),
        TextBlock(
            "also unusable",
            ((float("nan"), 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)),
            0.8,
        ),
    ]
    image = np.full((40, 60, 3), 255, dtype=np.uint8)

    candidates = extract_candidates(blocks, image)

    assert tuple(candidates) == FIELD_NAMES
    assert all(candidate.state is ExtractionState.MISSING for candidate in candidates.values())
    assert all(candidate.value is None for candidate in candidates.values())
    assert all(candidate.crop for candidate in candidates.values())


def _image() -> np.ndarray:
    return np.zeros((320, 800, 3), dtype=np.uint8)


@pytest.mark.parametrize(
    "line",
    [
        "Packaged by Old Tom Distillery, Bardstown, Kentucky",
        "Brewed by Old Tom Distillery, Bardstown, Kentucky",
        "Canned by Old Tom Distillery, Bardstown, Kentucky",
        "Blended by Old Tom Distillery, Bardstown, Kentucky",
        "Bottled for Old Tom Distillery, Bardstown, Kentucky",
        "Produced and bottled by Old Tom Distillery, Bardstown, Kentucky",
    ],
)
def test_real_label_bottling_phrases_are_recognised(line: str) -> None:
    """Labels say more than "bottled by"; every common verb must locate the field."""

    candidates = extract_candidates([_block(line, 35, 151, 620, 170)], _image())

    bottler = candidates["bottler"]
    assert bottler.state is ExtractionState.FOUND
    assert "Old Tom Distillery" in (bottler.value or "")


def test_bottling_phrase_prefix_is_stripped_before_comparison() -> None:
    """The longer phrase must win, or "produced and bottled by" leaks into the value."""

    assert normalize_bottler_text("Produced and bottled by Old Tom Distillery") == (
        normalize_bottler_text("Bottled by Old Tom Distillery")
    )
    assert normalize_bottler_text("Packaged by Old Tom Distillery") == "old tom distillery"


def test_origin_split_across_two_lines_is_joined() -> None:
    """ "PRODUCT OF" above "FRANCE" is one value the label happened to wrap."""

    candidates = extract_candidates(
        [
            _block("PRODUCT OF", 35, 174, 200, 193),
            _block("FRANCE", 35, 196, 180, 215),
        ],
        _image(),
    )

    origin = candidates["origin_country"]
    assert origin.state is ExtractionState.FOUND
    assert "FRANCE" in (origin.value or "")


def test_complete_origin_line_does_not_absorb_the_line_below_it() -> None:
    """A finished statement must not swallow unrelated label text."""

    candidates = extract_candidates(
        [
            _block("Product of Scotland", 35, 174, 260, 193),
            _block("FINE SPIRITS SINCE 1890", 35, 196, 300, 215),
        ],
        _image(),
    )

    assert candidates["origin_country"].value == "Product of Scotland"
