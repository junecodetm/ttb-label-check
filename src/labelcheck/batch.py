from __future__ import annotations

import csv
import io
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Protocol

import labelcheck.ocr
import labelcheck.pipeline
from labelcheck.models import ApplicationRecord, LabelReport, Status

MANIFEST_COLUMNS = (
    "filename",
    "brand_name",
    "class_type",
    "alcohol_content",
    "net_contents",
    "bottler",
    "origin_country",
)
VERIFICATION_FIELDS = (
    "brand_name",
    "class_type",
    "alcohol_content",
    "net_contents",
    "bottler",
    "origin_country",
    "government_warning",
    "government_warning_prefix",
    "government_warning_bold",
    "government_warning_type_size",
)
MAX_WORKERS = 8

MISSING_IMAGE_ERROR = (
    "Image not uploaded: this file is listed in the application CSV but was not uploaded."
)
MISSING_MANIFEST_ERROR = (
    "No matching manifest row: this image was uploaded but is not listed in the application CSV."
)
PROCESSING_ERROR = (
    "This label could not be checked. Try a clear, straight-on image in better light, "
    "then run the batch again."
)

_REQUIRED_COLUMNS = MANIFEST_COLUMNS[:-1]
_SEVERITY_RANK = {
    Status.FAIL: 0,
    Status.REVIEW: 1,
    Status.NOT_EVALUATED: 2,
    Status.PASS: 3,
}


class ManifestError(ValueError):
    """Give the UI one safe, actionable explanation for an unusable manifest."""


class BatchInputError(ValueError):
    """Stop ambiguous image-to-application pairings before any label is checked."""


class VerifyCallable(Protocol):
    def __call__(self, image_bytes: bytes, expected: ApplicationRecord) -> LabelReport: ...


ProgressCallback = Callable[[int, int], None]


@dataclass(frozen=True, slots=True)
class ManifestRow:
    """Keep the source filename beside the pipeline-ready application record."""

    filename: str
    application: ApplicationRecord


@dataclass(frozen=True, slots=True)
class UploadedImage:
    """Carry upload bytes through workers without creating a filesystem path."""

    filename: str
    image_bytes: bytes


@dataclass(frozen=True, slots=True)
class BatchResult:
    """Represent every input exactly once, including inputs that could not be paired."""

    filename: str
    application: ApplicationRecord | None = None
    report: LabelReport | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        if not self.filename.strip():
            raise ValueError("filename must not be blank")
        if (self.report is None) == (self.error is None):
            raise ValueError("a batch result must contain exactly one of report or error")

    @property
    def status(self) -> Status:
        """Sort visible errors with failures while preserving verified report status."""

        if self.error is not None:
            return Status.NOT_EVALUATED
        if self.report is None:  # Guarded by __post_init__; keeps the property total for typing.
            raise RuntimeError("batch result has neither a report nor an error")
        status = self.report.overall_status
        if status in {Status.FAIL, Status.REVIEW}:
            return status
        if not set(VERIFICATION_FIELDS).issubset(self.report.results):
            return Status.NOT_EVALUATED
        return status


@dataclass(frozen=True, slots=True)
class _WorkItem:
    order: int
    manifest: ManifestRow
    image: UploadedImage


def parse_manifest(csv_data: bytes | str) -> list[ManifestRow]:
    """Reject ambiguous application data rather than silently pairing the wrong label."""

    if isinstance(csv_data, bytes):
        try:
            text = csv_data.decode("utf-8-sig")
        except UnicodeDecodeError as error:
            raise ManifestError("The application CSV must use UTF-8 text.") from error
    elif isinstance(csv_data, str):
        text = csv_data.removeprefix("\ufeff")
    else:
        raise TypeError("csv_data must be bytes or text")

    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
    try:
        header = next(reader)
    except StopIteration as error:
        raise ManifestError("The application CSV needs a header row.") from error
    except csv.Error as error:
        raise ManifestError("The application CSV could not be read.") from error

    if tuple(header) != MANIFEST_COLUMNS:
        expected = ", ".join(MANIFEST_COLUMNS)
        raise ManifestError(
            f"The application CSV columns must appear in exactly this order: {expected}."
        )

    rows: list[ManifestRow] = []
    seen_filenames: set[str] = set()
    try:
        for line_number, values in enumerate(reader, start=2):
            if not values or all(not value.strip() for value in values):
                continue
            if len(values) != len(MANIFEST_COLUMNS):
                raise ManifestError(
                    f"Row {line_number} must contain {len(MANIFEST_COLUMNS)} values."
                )
            cleaned = dict(zip(MANIFEST_COLUMNS, (value.strip() for value in values), strict=True))
            missing = [column for column in _REQUIRED_COLUMNS if not cleaned[column]]
            if missing:
                names = ", ".join(missing)
                raise ManifestError(f"Row {line_number} is missing required values: {names}.")

            filename_key = _filename_key(cleaned["filename"])
            if filename_key in seen_filenames:
                raise ManifestError(
                    f"Row {line_number} repeats filename {cleaned['filename']!r}. "
                    "Filenames must be unique even when letter case differs."
                )
            seen_filenames.add(filename_key)
            rows.append(
                ManifestRow(
                    filename=cleaned["filename"],
                    application=ApplicationRecord(
                        brand_name=cleaned["brand_name"],
                        class_type=cleaned["class_type"],
                        alcohol_content=cleaned["alcohol_content"],
                        net_contents=cleaned["net_contents"],
                        bottler=cleaned["bottler"],
                        origin_country=cleaned["origin_country"] or None,
                    ),
                )
            )
    except csv.Error as error:
        raise ManifestError("The application CSV could not be read.") from error
    return rows


def sort_results(results: Sequence[BatchResult]) -> list[BatchResult]:
    """Keep urgent and unresolved work ahead of completed passing labels."""

    return sorted(
        results,
        key=lambda result: (
            _SEVERITY_RANK[Status.FAIL]
            if result.error is not None
            else _SEVERITY_RANK[result.status]
        ),
    )


def run_batch(
    images: Mapping[str, bytes] | Sequence[UploadedImage],
    manifest: Sequence[ManifestRow],
    *,
    verify_callable: VerifyCallable | None = None,
    max_workers: int = MAX_WORKERS,
    progress_callback: ProgressCallback | None = None,
) -> list[BatchResult]:
    """Reconcile first, then check matched labels concurrently in one shared process."""

    if not isinstance(max_workers, int) or isinstance(max_workers, bool) or max_workers < 1:
        raise ValueError("max_workers must be a positive integer")

    uploads = _coerce_uploads(images)
    work_items, indexed_results = _reconcile(uploads, manifest)
    total = len(work_items) + len(indexed_results)
    completed = len(indexed_results)
    if progress_callback is not None:
        progress_callback(completed, total)

    if not work_items:
        return sort_results([result for _, result in indexed_results])

    if verify_callable is None:
        labelcheck.ocr.warm()
        verifier: VerifyCallable = labelcheck.pipeline.verify
    else:
        verifier = verify_callable

    worker_count = min(MAX_WORKERS, max_workers, len(work_items))
    with ThreadPoolExecutor(
        max_workers=worker_count,
        thread_name_prefix="labelcheck-batch",
    ) as executor:
        futures = {
            executor.submit(
                verifier,
                item.image.image_bytes,
                item.manifest.application,
            ): item
            for item in work_items
        }
        for future in as_completed(futures):
            item = futures[future]
            try:
                report = future.result()
                if not isinstance(report, LabelReport):
                    raise TypeError("verify callable must return LabelReport")
                result = BatchResult(
                    filename=item.manifest.filename,
                    application=item.manifest.application,
                    report=report,
                )
            except Exception:
                result = BatchResult(
                    filename=item.manifest.filename,
                    application=item.manifest.application,
                    error=PROCESSING_ERROR,
                )
            indexed_results.append((item.order, result))
            completed += 1
            if progress_callback is not None:
                progress_callback(completed, total)

    ordered = [result for _, result in sorted(indexed_results, key=lambda item: item[0])]
    return sort_results(ordered)


def _filename_key(filename: str) -> str:
    return filename.casefold()


def _coerce_uploads(
    images: Mapping[str, bytes] | Sequence[UploadedImage],
) -> list[UploadedImage]:
    if isinstance(images, Mapping):
        candidates = [
            UploadedImage(filename, bytes(image_bytes)) for filename, image_bytes in images.items()
        ]
    elif isinstance(images, Sequence) and not isinstance(images, (str, bytes, bytearray)):
        candidates = list(images)
    else:
        raise TypeError("images must be a filename-to-bytes mapping or uploaded image sequence")

    uploads: list[UploadedImage] = []
    seen_filenames: set[str] = set()
    for candidate in candidates:
        if not isinstance(candidate, UploadedImage):
            raise TypeError("image sequences must contain UploadedImage values")
        filename = candidate.filename.strip()
        if not filename:
            raise BatchInputError("Every uploaded image needs a filename.")
        if not isinstance(candidate.image_bytes, bytes):
            raise TypeError("uploaded image data must be bytes")
        filename_key = _filename_key(filename)
        if filename_key in seen_filenames:
            raise BatchInputError(
                f"More than one uploaded image is named {filename!r} when letter case is ignored."
            )
        seen_filenames.add(filename_key)
        uploads.append(UploadedImage(filename, candidate.image_bytes))
    return uploads


def _reconcile(
    uploads: Sequence[UploadedImage],
    manifest: Sequence[ManifestRow],
) -> tuple[list[_WorkItem], list[tuple[int, BatchResult]]]:
    upload_by_name = {_filename_key(upload.filename): upload for upload in uploads}
    matched_uploads: set[str] = set()
    seen_manifest: set[str] = set()
    work_items: list[_WorkItem] = []
    results: list[tuple[int, BatchResult]] = []

    for order, row in enumerate(manifest):
        if not isinstance(row, ManifestRow):
            raise TypeError("manifest sequences must contain ManifestRow values")
        filename_key = _filename_key(row.filename)
        if filename_key in seen_manifest:
            raise BatchInputError(
                f"The application CSV repeats filename {row.filename!r} "
                "when letter case is ignored."
            )
        seen_manifest.add(filename_key)
        upload = upload_by_name.get(filename_key)
        if upload is None:
            results.append(
                (
                    order,
                    BatchResult(
                        filename=row.filename,
                        application=row.application,
                        error=MISSING_IMAGE_ERROR,
                    ),
                )
            )
            continue
        matched_uploads.add(filename_key)
        work_items.append(_WorkItem(order=order, manifest=row, image=upload))

    next_order = len(manifest)
    for upload in uploads:
        if _filename_key(upload.filename) in matched_uploads:
            continue
        results.append(
            (
                next_order,
                BatchResult(
                    filename=upload.filename,
                    error=MISSING_MANIFEST_ERROR,
                ),
            )
        )
        next_order += 1
    return work_items, results
