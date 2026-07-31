from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIRECTORY = PROJECT_ROOT / ".bench_images"


def main() -> None:
    """Materialize deterministic fixtures only when a developer explicitly benchmarks."""

    sys.path.insert(0, str(PROJECT_ROOT / "src"))
    sys.path.insert(0, str(PROJECT_ROOT / "tests"))
    from fixture_factory import make_label

    variants = {
        "clean.png": {},
        "ornate.png": {"ornate": True},
        "rotated.png": {"rotation_degrees": 5.0},
        "glare.png": {"glare": True},
        "low_resolution.png": {"low_resolution": True},
        "combined_adversarial.png": {
            "ornate": True,
            "rotation_degrees": -4.0,
            "glare": True,
            "low_resolution": True,
        },
    }

    OUTPUT_DIRECTORY.mkdir(parents=True, exist_ok=True)
    for filename, options in variants.items():
        (OUTPUT_DIRECTORY / filename).write_bytes(make_label(**options))


if __name__ == "__main__":
    main()
