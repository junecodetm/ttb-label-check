from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum


class Status(StrEnum):
    """Keep verdict values stable for later UI and manifest serialization."""

    PASS = "PASS"
    REVIEW = "REVIEW"
    FAIL = "FAIL"
    NOT_EVALUATED = "NOT_EVALUATED"


BoundingBox = tuple[tuple[float, float], ...]


@dataclass(frozen=True, slots=True)
class TextBlock:
    """Retain geometry so a later perception layer can attach trustworthy evidence."""

    text: str
    bbox: BoundingBox
    confidence: float


@dataclass(frozen=True, slots=True)
class FieldResult:
    """Carry honest evidence for every field, including checks that could not run."""

    status: Status
    expected: str | None
    extracted: str | None
    confidence: float | None
    crop: object | None
    detail: str


@dataclass(frozen=True, slots=True)
class ApplicationRecord:
    """Mirror the batch-manifest schema so later ingestion needs no field translation."""

    brand_name: str
    class_type: str
    alcohol_content: str
    net_contents: str
    bottler: str
    origin_country: str | None = None


@dataclass(frozen=True, slots=True)
class LabelReport:
    """Derive the roll-up so callers cannot supply a status inconsistent with its fields."""

    results: Mapping[str, FieldResult]

    @property
    def overall_status(self) -> Status:
        """Summarize what ran while leaving skipped checks visible on their own results."""

        statuses = {result.status for result in self.results.values()}
        if Status.FAIL in statuses:
            return Status.FAIL
        if Status.REVIEW in statuses:
            return Status.REVIEW
        if Status.PASS in statuses:
            return Status.PASS
        return Status.NOT_EVALUATED

    @property
    def unevaluated_checks(self) -> tuple[str, ...]:
        """Expose skipped check names so aggregate displays cannot hide them."""

        return tuple(
            name
            for name, result in self.results.items()
            if result.status is Status.NOT_EVALUATED
        )
