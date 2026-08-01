"""Run one image through verify() and print the report, for checking real labels by hand.

    .venv/bin/python tools/check_label.py photo.jpg \
        --brand "(509) SPIRITS" --class-type "Canadian Whisky" --origin Canada
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from time import perf_counter

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    parser.add_argument("--brand", default="")
    parser.add_argument("--class-type", default="")
    parser.add_argument("--alcohol", default="")
    parser.add_argument("--net-contents", default="")
    parser.add_argument("--bottler", default="")
    parser.add_argument("--origin", default="")
    parser.add_argument("--show-text", action="store_true", help="print raw OCR lines")
    arguments = parser.parse_args()

    sys.path.insert(0, str(PROJECT_ROOT / "src"))
    from labelcheck import ocr, preprocess
    from labelcheck.models import ApplicationRecord
    from labelcheck.pipeline import verify

    image_bytes = arguments.image.read_bytes()
    record = ApplicationRecord(
        brand_name=arguments.brand,
        class_type=arguments.class_type,
        alcohol_content=arguments.alcohol,
        net_contents=arguments.net_contents,
        bottler=arguments.bottler,
        origin_country=arguments.origin or None,
    )

    ocr.warm()
    started = perf_counter()
    report = verify(image_bytes, record)
    elapsed = perf_counter() - started

    print(f"{arguments.image.name}: {elapsed:.2f}s  overall={report.overall_status.value}")
    for field_name, result in report.results.items():
        expected = result.expected or "-"
        extracted = result.extracted or "-"
        print(f"  {field_name:<30} {result.status.value:<14} read={extracted[:60]!r}")
        if result.status.value not in {"PASS", "NOT_EVALUATED"}:
            print(f"  {'':<30} {'':<14} want={expected[:60]!r}")

    if arguments.show_text:
        print("\nOCR lines:")
        for block in ocr.recognize(preprocess.preprocess_image(image_bytes)):
            print(f"  {block.confidence:.2f}  {block.text}")


if __name__ == "__main__":
    main()
