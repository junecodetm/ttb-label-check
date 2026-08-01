"""Measure a peak-season batch end to end: wall time, throughput and peak memory.

Sarah Chen's requirement is 200-300 label applications dumped at once, so the
figure that matters is not per-label latency but whether the whole queue finishes
in a time an agent will wait for, inside the memory a free-tier host allows.

    .venv/bin/python tools/bench_batch.py --count 300
"""

from __future__ import annotations

import argparse
import resource
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def peak_rss_mb() -> float:
    """Peak resident set size. macOS reports bytes here; Linux reports kilobytes."""

    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    divisor = 1024 * 1024 if sys.platform == "darwin" else 1024
    return peak / divisor


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=300)
    parser.add_argument("--workers", type=int, default=None)
    arguments = parser.parse_args()

    sys.path.insert(0, str(PROJECT_ROOT / "src"))
    sys.path.insert(0, str(PROJECT_ROOT / "tests"))
    from fixture_factory import make_label, sample_application_record

    from labelcheck import ocr
    from labelcheck.batch import MAX_WORKERS, UploadedImage, run_batch
    from labelcheck.models import Status

    workers = arguments.workers or MAX_WORKERS
    record = sample_application_record()

    # Six variants cycled so the batch is not 300 copies of one easy image.
    variants: tuple[dict[str, object], ...] = (
        {},
        {"ornate": True},
        {"rotation_degrees": 5.0},
        {"glare": True},
        {"low_resolution": True},
        {"ornate": True, "rotation_degrees": -4.0, "glare": True},
    )

    build_started = time.perf_counter()
    images: list[UploadedImage] = []
    manifest_rows = []
    for index in range(arguments.count):
        options = variants[index % len(variants)]
        filename = f"label-{index:04d}.png"
        images.append(UploadedImage(filename, make_label(**options)))
        manifest_rows.append(_manifest_row(filename, record))
    build_seconds = time.perf_counter() - build_started

    total_bytes = sum(len(image.image_bytes) for image in images)
    print(
        f"prepared {len(images)} labels in {build_seconds:.1f}s "
        f"({total_bytes / (1024 * 1024):.0f}MB of image bytes), workers={workers}"
    )

    ocr.warm()
    rss_before = peak_rss_mb()

    completed_at: list[float] = []

    def on_progress(completed: int, _total: int) -> None:
        completed_at.append(time.perf_counter())
        if completed % 25 == 0:
            print(f"  {completed}/{arguments.count} at {completed_at[-1] - started:.1f}s")

    started = time.perf_counter()
    results = run_batch(images, manifest_rows, max_workers=workers, progress_callback=on_progress)
    elapsed = time.perf_counter() - started

    verdicts: dict[Status, int] = {}
    errors = 0
    for result in results:
        if result.error is not None:
            errors += 1
            continue
        verdicts[result.status] = verdicts.get(result.status, 0) + 1

    print(
        f"\nbatch of {len(results)}: {elapsed:.1f}s total, "
        f"{elapsed / max(len(results), 1):.3f}s per label, "
        f"{len(results) / elapsed:.2f} labels/second"
    )
    print(f"peak RSS {peak_rss_mb():.0f}MB (before batch {rss_before:.0f}MB)")
    print(f"verdicts {[(status.value, count) for status, count in sorted(verdicts.items())]}")
    print(f"errors {errors}")

    if completed_at:
        first_result_delay = completed_at[0] - started
        print(f"first result after {first_result_delay:.1f}s")


def _manifest_row(filename: str, record: object):
    from labelcheck.batch import ManifestRow

    return ManifestRow(filename=filename, application=record)  # type: ignore[arg-type]


if __name__ == "__main__":
    main()
