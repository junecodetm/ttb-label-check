"""Render the sample labels the app ships so an evaluator can try it in one click.

Unlike .bench_images/, these ARE committed: the deployed app has no other way to
show a working result to someone who does not happen to have a bottle photograph
and six matching application values to hand.

    .venv/bin/python tools/make_samples.py
"""

from __future__ import annotations

import csv
import sys
from dataclasses import replace
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIRECTORY = PROJECT_ROOT / "samples"


def main() -> None:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))
    sys.path.insert(0, str(PROJECT_ROOT / "tests"))
    from fixture_factory import make_label, sample_application_record

    from labelcheck.batch import MANIFEST_COLUMNS
    from labelcheck.config import GOVERNMENT_WARNING

    record = sample_application_record()

    # Each sample is one of the brief's own acceptance cases, so the demo shows the
    # three verdicts rather than three variations of green.
    samples = {
        # Sarah Chen's ordinary case: everything matches.
        "compliant-bourbon.png": (make_label(), record),
        # Jenny Park rejected a label for exactly this.
        "title-case-warning.png": (
            make_label(
                warning_text=GOVERNMENT_WARNING.replace(
                    "GOVERNMENT WARNING:", "Government Warning:"
                )
            ),
            record,
        ),
        # Jenny Park again: weird angles, bad lighting, glare on the bottle.
        "angled-and-glared.png": (
            make_label(rotation_degrees=4.0, glare=True, ornate=True),
            record,
        ),
        # Dave Morrison: obviously the same thing, different capitalisation.
        "brand-case-mismatch.png": (
            make_label(),
            replace(record, brand_name="Old Tom Distillery"),
        ),
    }

    OUTPUT_DIRECTORY.mkdir(parents=True, exist_ok=True)
    rows = []
    for filename, (image_bytes, expected) in samples.items():
        (OUTPUT_DIRECTORY / filename).write_bytes(image_bytes)
        rows.append(
            (
                filename,
                expected.brand_name,
                expected.class_type,
                expected.alcohol_content,
                expected.net_contents,
                expected.bottler,
                expected.origin_country or "",
            )
        )

    manifest_path = OUTPUT_DIRECTORY / "application-values.csv"
    with manifest_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(MANIFEST_COLUMNS)
        writer.writerows(rows)

    print(f"wrote {len(rows)} sample labels and {manifest_path.name} to {OUTPUT_DIRECTORY}")


if __name__ == "__main__":
    main()
