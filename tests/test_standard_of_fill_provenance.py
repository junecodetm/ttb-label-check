"""Pin the standards-of-fill constants to their CFR provenance anchors.

Mirrors tests/test_warning_provenance.py: the authorized-size frozensets in config.py
must equal, value for value, the (a)-lists in the plain-text extracts fetched from the
eCFR versioner API (docs/cfr/27-cfr-5-203.txt and 27-cfr-4-72.txt). A transcription slip
in either direction would silently flip the container-size verdict for that size.
"""

import re
from decimal import Decimal
from pathlib import Path

from labelcheck.config import (
    SPIRITS_STANDARDS_OF_FILL_ML,
    WARNING_TYPE_SIZE_TABLE,
    WINE_FDA_JURISDICTION_MIN_ABV,
    WINE_LARGE_FORMAT_MIN_ML,
    WINE_LARGE_FORMAT_STEP_ML,
    WINE_STANDARDS_OF_FILL_ML,
)

_CFR_DIR = Path(__file__).resolve().parent.parent / "docs" / "cfr"
_LIST_ITEM = re.compile(r"^\((\d+)\) ([\d.]+) (Liters?|liters?|mL|milliliters)\.$")


def _authorized_sizes_ml(anchor_name: str) -> set[Decimal]:
    sizes: set[Decimal] = set()
    for line in (_CFR_DIR / anchor_name).read_text().splitlines():
        match = _LIST_ITEM.match(line.strip())
        if match is None:
            continue
        value = Decimal(match.group(2))
        if match.group(3).lower().startswith("l"):
            value *= Decimal("1000")
        sizes.add(value)
    return sizes


def test_spirits_standards_match_the_cfr_anchor_exactly() -> None:
    anchored = _authorized_sizes_ml("27-cfr-5-203.txt")
    assert len(anchored) == 25, "anchor no longer parses to the 25 sizes 5.203(a) lists"
    assert set(SPIRITS_STANDARDS_OF_FILL_ML) == anchored


def test_wine_standards_match_the_cfr_anchor_exactly() -> None:
    anchored = _authorized_sizes_ml("27-cfr-4-72.txt")
    assert len(anchored) == 25, "anchor no longer parses to the 25 sizes 4.72(a) lists"
    assert set(WINE_STANDARDS_OF_FILL_ML) == anchored


def test_wine_large_format_rule_matches_4_72_b() -> None:
    anchor_text = (_CFR_DIR / "27-cfr-4-72.txt").read_text()
    assert "4 liters or larger" in anchor_text
    assert "even liters" in anchor_text
    assert WINE_LARGE_FORMAT_MIN_ML == Decimal("4000")
    assert WINE_LARGE_FORMAT_STEP_ML == Decimal("1000")


def test_warning_type_size_table_matches_the_16_22_anchor() -> None:
    anchor_text = (_CFR_DIR / "27-cfr-16-22.txt").read_text()
    tier_lines = re.findall(r"^(\d) millimeters? — (\d+)$", anchor_text, re.MULTILINE)
    assert [(int(size), int(chars)) for size, chars in tier_lines] == [
        (size_mm, chars_per_inch) for _, size_mm, chars_per_inch in WARNING_TYPE_SIZE_TABLE
    ]
    small_ceiling, medium_ceiling, large_ceiling = (row[0] for row in WARNING_TYPE_SIZE_TABLE)
    assert f"Containers of {small_ceiling} milliliters (8 fl. oz.) or less" in anchor_text
    assert f"more than {small_ceiling} milliliters (8 fl. oz.) up to 3 liters" in anchor_text
    assert medium_ceiling == Decimal("3000")
    assert "more than 3 liters (101 fl. oz.)" in anchor_text
    assert large_ceiling is None


def test_wine_fda_jurisdiction_floor_matches_the_4_10_anchor() -> None:
    anchor_text = (_CFR_DIR / "27-cfr-4-10.txt").read_text()
    assert (
        f"not less than {WINE_FDA_JURISDICTION_MIN_ABV} percent and not more than 24 percent"
        in anchor_text
    )
