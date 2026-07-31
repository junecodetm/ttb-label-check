from pathlib import Path

from labelcheck.config import GOVERNMENT_WARNING


def test_government_warning_matches_the_verified_cfr_payload_byte_for_byte() -> None:
    provenance_file = Path(__file__).parents[1] / "docs" / "cfr" / "27-cfr-16-21.txt"
    payload_lines = [
        line
        for line in provenance_file.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    ]

    assert payload_lines == [GOVERNMENT_WARNING]
