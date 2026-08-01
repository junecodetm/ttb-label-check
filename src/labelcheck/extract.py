from __future__ import annotations

import math
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum

import cv2
import numpy as np

from labelcheck.config import (
    ABV_MARKER_SIGNAL_PATTERN,
    BEVERAGE_CLASS_KEYWORDS,
    BOTTLER_MAX_CONTINUATION_LINES,
    BOTTLER_MAX_LINE_GAP_MULTIPLIER,
    BOTTLER_PREFIX_TOKEN_SEQUENCES,
    BRAND_AMBIGUITY_HEIGHT_RATIO,
    BRAND_MAX_CHARACTERS,
    BRAND_MULTILINE_MAX_GAP_RATIO,
    BRAND_MULTILINE_MIN_HORIZONTAL_OVERLAP_RATIO,
    EVIDENCE_CROP_PADDING_PX,
    GOVERNMENT_WARNING,
    NUMBER_PATTERN,
    OCR_LINE_CENTER_TOLERANCE_RATIO,
    OCR_LINE_MIN_VERTICAL_OVERLAP_RATIO,
    ORIGIN_MAX_CONTINUATION_LINES,
    ORIGIN_MAX_LINE_GAP_MULTIPLIER,
    WARNING_FALLBACK_MIN_CUES,
    WARNING_MAX_LINE_GAP_MULTIPLIER,
)
from labelcheck.models import BoundingBox, TextBlock
from labelcheck.normalize import normalize_identity_text, normalize_origin_text, parse_abv

FIELD_NAMES: tuple[str, ...] = (
    "brand_name",
    "class_type",
    "alcohol_content",
    "net_contents",
    "bottler",
    "origin_country",
    "government_warning",
)


class ExtractionState(StrEnum):
    """Distinguish missing perception evidence from conflicting evidence."""

    FOUND = "FOUND"
    AMBIGUOUS = "AMBIGUOUS"
    MISSING = "MISSING"


@dataclass(frozen=True, slots=True)
class FieldCandidate:
    """Keep OCR provenance attached until field-specific rules create verdicts."""

    value: str | None
    blocks: tuple[TextBlock, ...]
    bbox: BoundingBox
    ocr_confidence: float | None
    crop: bytes
    state: ExtractionState
    alternatives: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _LocatedBlock:
    block: TextBlock
    left: float
    top: float
    right: float
    bottom: float

    @property
    def height(self) -> float:
        return self.bottom - self.top

    @property
    def center_y(self) -> float:
        return (self.top + self.bottom) / 2.0


@dataclass(frozen=True, slots=True)
class _Line:
    text: str
    members: tuple[_LocatedBlock, ...]
    left: float
    top: float
    right: float
    bottom: float
    confidence: float

    @property
    def height(self) -> float:
        return self.bottom - self.top


@dataclass(frozen=True, slots=True)
class _Selection:
    value: str
    line_indices: tuple[int, ...]


_EXPLICIT_PATTERNS = {
    "brand_name": re.compile(r"^\s*brand\s*(?:name)?\s*[:\-]\s*(.*)$", re.IGNORECASE),
    "class_type": re.compile(r"^\s*class\s*(?:/|and)?\s*type\s*[:\-]\s*(.*)$", re.IGNORECASE),
    "alcohol_content": re.compile(r"^\s*alcohol\s+content\s*[:\-]\s*(.*)$", re.IGNORECASE),
    "net_contents": re.compile(r"^\s*net\s+contents?\s*[:\-]\s*(.*)$", re.IGNORECASE),
    "bottler": re.compile(r"^\s*bottler\s*[:\-]\s*(.*)$", re.IGNORECASE),
    "origin_country": re.compile(
        r"^\s*(?:country\s+of\s+origin|origin\s+country)\s*[:\-]\s*(.*)$",
        re.IGNORECASE,
    ),
}
_ANY_EXPLICIT_PATTERN = re.compile(
    r"^\s*(?:brand\s*(?:name)?|class\s*(?:/|and)?\s*type|alcohol\s+content|"
    r"net\s+contents?|bottler|country\s+of\s+origin|origin\s+country)\s*[:\-]",
    re.IGNORECASE,
)
_NET_CONTENT_CANDIDATE = re.compile(
    rf"(?<![0-9A-Za-z.])(?:{NUMBER_PATTERN})\s*"
    r"(?:fl\.?\s*oz\.?|ml|millilit(?:er|re)s?|l|lit(?:er|re)s?)(?![A-Za-z])",
    re.IGNORECASE,
)
# Built from the same prefix table the comparison strips, so the two cannot drift.
# Words are joined with \s* rather than a literal space because OCR reads real label
# typography as "IMPORTED&BOTTLEDBYSAHALEE" often enough to matter.
_BOTTLER_SIGNAL = re.compile(
    r"\b(?:"
    + "|".join(
        r"\s*".join(re.escape(token) for token in tokens)
        for tokens in sorted(
            BOTTLER_PREFIX_TOKEN_SEQUENCES,
            key=lambda tokens: len(" ".join(tokens)),
            reverse=True,
        )
    )
    + r")",
    re.IGNORECASE,
)
_ORIGIN_SIGNAL = re.compile(
    r"^\s*(?:product\s+of|produce\s+of|made\s+in|produced\s+in|bottled\s+in"
    r"|distilled\s+in|brewed\s+in|vinted\s+in|grown\s+in|imported\s+from"
    r"|country\s+of\s+origin)\b",
    re.IGNORECASE,
)
# \s* not \s+: OCR reads stylised label text as "GOVERNMENTWARNING:" often enough
# that requiring the space loses the anchor, and with it the whole warning check.
_WARNING_ANCHOR = re.compile(r"\bgovernment\s*warning\s*:", re.IGNORECASE)
_WARNING_CUES = (
    "surgeon general",
    "pregnancy",
    "birth defects",
    "consumption",
    "machinery",
    "health problems",
)


def _validate_image(image: np.ndarray) -> None:
    if (
        not isinstance(image, np.ndarray)
        or image.dtype != np.uint8
        or image.ndim != 3
        or image.shape[2] != 3
        or image.size == 0
    ):
        raise ValueError("extraction image must be a non-empty uint8 BGR array")


def _locate_blocks(blocks: Sequence[TextBlock], width: int, height: int) -> list[_LocatedBlock]:
    located: list[_LocatedBlock] = []
    seen: set[tuple[object, ...]] = set()
    for block in blocks:
        if not isinstance(block.text, str) or not block.text.strip():
            continue
        try:
            points = np.asarray(block.bbox, dtype=np.float64)
            confidence = float(block.confidence)
        except (TypeError, ValueError, OverflowError):
            continue
        if (
            points.ndim != 2
            or points.shape[0] < 2
            or points.shape[1] != 2
            or not np.isfinite(points).all()
            or not math.isfinite(confidence)
            or not 0.0 <= confidence <= 1.0
        ):
            continue

        left = max(0.0, float(points[:, 0].min()))
        top = max(0.0, float(points[:, 1].min()))
        right = min(float(width), float(points[:, 0].max()))
        bottom = min(float(height), float(points[:, 1].max()))
        if right <= left or bottom <= top:
            continue
        duplicate_key = (
            block.text.strip(),
            round(left, 1),
            round(top, 1),
            round(right, 1),
            round(bottom, 1),
        )
        if duplicate_key in seen:
            continue
        seen.add(duplicate_key)
        located.append(_LocatedBlock(block, left, top, right, bottom))
    return located


def _same_line(block: _LocatedBlock, members: list[_LocatedBlock]) -> bool:
    top = min(member.top for member in members)
    bottom = max(member.bottom for member in members)
    line_height = bottom - top
    overlap = min(bottom, block.bottom) - max(top, block.top)
    overlap_ratio = overlap / min(line_height, block.height) if overlap > 0 else 0.0
    center = (top + bottom) / 2.0
    center_distance = abs(center - block.center_y)
    center_limit = min(line_height, block.height) * OCR_LINE_CENTER_TOLERANCE_RATIO
    return overlap_ratio >= OCR_LINE_MIN_VERTICAL_OVERLAP_RATIO or center_distance <= center_limit


def _group_lines(blocks: Sequence[TextBlock], width: int, height: int) -> list[_Line]:
    groups: list[list[_LocatedBlock]] = []
    for block in sorted(
        _locate_blocks(blocks, width, height), key=lambda item: (item.top, item.left)
    ):
        matching_group: list[_LocatedBlock] | None = None
        for group in reversed(groups):
            if _same_line(block, group):
                matching_group = group
                break
            if block.top > max(member.bottom for member in group) + block.height:
                break
        if matching_group is None:
            groups.append([block])
        else:
            matching_group.append(block)

    lines: list[_Line] = []
    for group in groups:
        ordered = tuple(sorted(group, key=lambda item: item.left))
        text = " ".join(item.block.text.strip() for item in ordered)
        character_count = sum(max(len(item.block.text.strip()), 1) for item in ordered)
        confidence = (
            sum(item.block.confidence * max(len(item.block.text.strip()), 1) for item in ordered)
            / character_count
        )
        lines.append(
            _Line(
                text=text,
                members=ordered,
                left=min(item.left for item in ordered),
                top=min(item.top for item in ordered),
                right=max(item.right for item in ordered),
                bottom=max(item.bottom for item in ordered),
                confidence=float(confidence),
            )
        )
    return sorted(lines, key=lambda line: (line.top, line.left))


def _explicit_selections(lines: Sequence[_Line], field_name: str) -> list[_Selection]:
    pattern = _EXPLICIT_PATTERNS[field_name]
    selections: list[_Selection] = []
    for index, line in enumerate(lines):
        match = pattern.match(line.text)
        if match is None:
            continue
        inline_value = match.group(1).strip()
        if inline_value:
            selections.append(_Selection(inline_value, (index,)))
        elif index + 1 < len(lines):
            selections.append(_Selection(lines[index + 1].text.strip(), (index, index + 1)))
    return selections


def _starts_another_warning_selection(line: _Line) -> bool:
    return bool(_ANY_EXPLICIT_PATTERN.match(line.text) or _WARNING_ANCHOR.search(line.text))


def _warning_selections(lines: Sequence[_Line]) -> list[_Selection]:
    target_words = len(GOVERNMENT_WARNING.split())
    anchored: list[_Selection] = []
    for start, line in enumerate(lines):
        if _WARNING_ANCHOR.search(line.text) is None:
            continue
        anchored.append(
            _extend_with_continuation_lines(
                lines,
                _Selection(line.text, (start,)),
                max_continuation_lines=None,
                max_line_gap_multiplier=WARNING_MAX_LINE_GAP_MULTIPLIER,
                is_boundary=_starts_another_warning_selection,
                target_word_count=target_words,
            )
        )

    if anchored:
        return anchored

    normalized_lines = [normalize_identity_text(line.text) for line in lines]
    cue_indices = [
        index
        for index, text in enumerate(normalized_lines)
        if any(cue in text for cue in _WARNING_CUES)
    ]
    cue_count = sum(any(cue in text for text in normalized_lines) for cue in _WARNING_CUES)
    if cue_indices and cue_count >= WARNING_FALLBACK_MIN_CUES:
        start = min(cue_indices)
        end = max(cue_indices)
        indices = tuple(range(start, end + 1))
        return [_Selection("\n".join(lines[index].text for index in indices), indices)]
    return []


def _alcohol_selections(lines: Sequence[_Line]) -> list[_Selection]:
    explicit = _explicit_selections(lines, "alcohol_content")
    if explicit:
        return explicit

    selections: list[_Selection] = []
    for index, line in enumerate(lines):
        try:
            abv = parse_abv(line.text)
        except ValueError:
            if re.search(ABV_MARKER_SIGNAL_PATTERN, line.text, flags=re.IGNORECASE):
                selections.append(_Selection(line.text.strip(), (index,)))
            continue
        if abv is not None:
            selections.append(_Selection(line.text.strip(), (index,)))
    return selections


def _net_content_selections(lines: Sequence[_Line]) -> list[_Selection]:
    explicit = _explicit_selections(lines, "net_contents")
    if explicit:
        return explicit

    selections: list[_Selection] = []
    for index, line in enumerate(lines):
        for match in _NET_CONTENT_CANDIDATE.finditer(line.text):
            selections.append(_Selection(match.group(0).strip(), (index,)))
    return selections


def _bottler_selections(lines: Sequence[_Line]) -> list[_Selection]:
    explicit = _explicit_selections(lines, "bottler")
    selections = explicit or [
        _Selection(line.text.strip(), (index,))
        for index, line in enumerate(lines)
        if _BOTTLER_SIGNAL.search(line.text)
    ]

    return [
        _extend_with_continuation_lines(
            lines,
            selection,
            max_continuation_lines=BOTTLER_MAX_CONTINUATION_LINES,
            max_line_gap_multiplier=BOTTLER_MAX_LINE_GAP_MULTIPLIER,
            is_boundary=_starts_a_different_field,
        )
        for selection in selections
    ]


def _starts_a_different_field(line: _Line) -> bool:
    """Stop a wrapped value before it swallows the next field on the label."""

    return bool(
        _ANY_EXPLICIT_PATTERN.match(line.text)
        or _WARNING_ANCHOR.search(line.text)
        or _ORIGIN_SIGNAL.search(line.text)
        or _BOTTLER_SIGNAL.search(line.text)
        or re.search(ABV_MARKER_SIGNAL_PATTERN, line.text, flags=re.IGNORECASE)
        or _NET_CONTENT_CANDIDATE.search(line.text)
    )


def _extend_with_continuation_lines(
    lines: Sequence[_Line],
    selection: _Selection,
    *,
    max_continuation_lines: int | None,
    max_line_gap_multiplier: float,
    is_boundary: Callable[[_Line], bool],
    target_word_count: int | None = None,
) -> _Selection:
    """Join the wrapped lines of one value so a split address or origin reads whole."""

    indices = list(selection.line_indices)
    values = [selection.value]
    word_count = len(selection.value.split())
    previous = lines[indices[-1]]
    for index in range(indices[-1] + 1, len(lines)):
        if target_word_count is not None and word_count >= target_word_count:
            break
        if (
            max_continuation_lines is not None
            and len(indices) - len(selection.line_indices) >= max_continuation_lines
        ):
            break
        following = lines[index]
        gap = following.top - previous.bottom
        if gap > max(previous.height, following.height) * max_line_gap_multiplier:
            break
        if is_boundary(following):
            break
        indices.append(index)
        values.append(following.text.strip())
        word_count += len(following.text.split())
        previous = following
    return _Selection("\n".join(values), tuple(indices))


def _origin_selections(lines: Sequence[_Line]) -> list[_Selection]:
    explicit = _explicit_selections(lines, "origin_country")
    if explicit:
        return explicit

    selections = [
        _Selection(line.text.strip(), (index,))
        for index, line in enumerate(lines)
        if _ORIGIN_SIGNAL.search(line.text)
    ]
    # Only a bare prefix needs the next line: "PRODUCT OF" above "FRANCE" is one
    # value split in two. A complete statement already names the country, and
    # extending it would let unrelated label text contaminate the comparison.
    return [
        _extend_with_continuation_lines(
            lines,
            selection,
            max_continuation_lines=ORIGIN_MAX_CONTINUATION_LINES,
            max_line_gap_multiplier=ORIGIN_MAX_LINE_GAP_MULTIPLIER,
            is_boundary=_starts_a_different_field,
        )
        if not normalize_origin_text(selection.value)
        else selection
        for selection in selections
    ]


def _class_selections(lines: Sequence[_Line], excluded_indices: set[int]) -> list[_Selection]:
    explicit = _explicit_selections(lines, "class_type")
    if explicit:
        return explicit

    ranked: list[tuple[tuple[int, int], int]] = []
    for index, line in enumerate(lines):
        if index in excluded_indices:
            continue
        normalized = normalize_identity_text(line.text)
        padded = f" {normalized} "
        matched_lengths = [
            len(keyword.split())
            for _canonical, keywords in BEVERAGE_CLASS_KEYWORDS
            for keyword in keywords
            if f" {keyword} " in padded
        ]
        if matched_lengths:
            ranked.append(((max(matched_lengths), len(matched_lengths)), index))
    if not ranked:
        return []
    best_score = max(score for score, _index in ranked)
    return [
        _Selection(lines[index].text.strip(), (index,))
        for score, index in ranked
        if score == best_score
    ]


def _brand_selections(lines: Sequence[_Line], excluded_indices: set[int]) -> list[_Selection]:
    explicit = _explicit_selections(lines, "brand_name")
    if explicit:
        return explicit

    eligible: list[tuple[int, _Line]] = []
    for index, line in enumerate(lines):
        text = line.text.strip()
        if index in excluded_indices or len(text) > BRAND_MAX_CHARACTERS:
            continue
        if not any(character.isalpha() for character in text):
            continue
        if _ANY_EXPLICIT_PATTERN.match(text) or _WARNING_ANCHOR.search(text):
            continue
        eligible.append((index, line))
    if not eligible:
        return []

    eligible.sort(key=lambda item: (item[1].height, -item[1].top, item[1].confidence), reverse=True)
    best_height = eligible[0][1].height
    contenders = [
        (index, line)
        for index, line in eligible
        if line.height >= best_height * BRAND_AMBIGUITY_HEIGHT_RATIO
    ]
    contenders.sort(key=lambda item: item[0])

    groups: list[list[tuple[int, _Line]]] = []
    for contender in contenders:
        if groups and _brand_lines_are_connected(groups[-1][-1], contender):
            groups[-1].append(contender)
        else:
            groups.append([contender])

    return [
        _Selection(
            " ".join(line.text.strip() for _index, line in group),
            tuple(index for index, _line in group),
        )
        for group in groups
    ]


def _brand_lines_are_connected(
    first: tuple[int, _Line],
    second: tuple[int, _Line],
) -> bool:
    first_index, first_line = first
    second_index, second_line = second
    if second_index != first_index + 1:
        return False

    gap = second_line.top - first_line.bottom
    if gap < 0 or gap > max(first_line.height, second_line.height) * BRAND_MULTILINE_MAX_GAP_RATIO:
        return False

    overlap = min(first_line.right, second_line.right) - max(first_line.left, second_line.left)
    minimum_width = min(
        first_line.right - first_line.left,
        second_line.right - second_line.left,
    )
    return overlap > 0 and overlap / minimum_width >= BRAND_MULTILINE_MIN_HORIZONTAL_OVERLAP_RATIO


def _selection_indices(selections: Sequence[_Selection]) -> set[int]:
    return {index for selection in selections for index in selection.line_indices}


def _bounds_for_indices(lines: Sequence[_Line], indices: Sequence[int]) -> tuple[float, ...]:
    selected = [lines[index] for index in sorted(set(indices))]
    return (
        min(line.left for line in selected),
        min(line.top for line in selected),
        max(line.right for line in selected),
        max(line.bottom for line in selected),
    )


def _bbox_from_bounds(bounds: tuple[float, ...]) -> BoundingBox:
    left, top, right, bottom = bounds
    return ((left, top), (right, top), (right, bottom), (left, bottom))


def _encode_crop(image: np.ndarray, bounds: tuple[float, ...]) -> bytes:
    left, top, right, bottom = bounds
    height, width = image.shape[:2]
    x1 = max(0, int(math.floor(left)) - EVIDENCE_CROP_PADDING_PX)
    y1 = max(0, int(math.floor(top)) - EVIDENCE_CROP_PADDING_PX)
    x2 = min(width, int(math.ceil(right)) + EVIDENCE_CROP_PADDING_PX)
    y2 = min(height, int(math.ceil(bottom)) + EVIDENCE_CROP_PADDING_PX)
    if x2 <= x1 or y2 <= y1:
        x1, y1, x2, y2 = 0, 0, width, height
    successful, encoded = cv2.imencode(".png", image[y1:y2, x1:x2])
    if not successful or encoded.size == 0:
        raise ValueError("evidence crop could not be encoded in memory")
    return encoded.tobytes()


def _candidate_from_selections(
    selections: Sequence[_Selection],
    lines: Sequence[_Line],
    image: np.ndarray,
    fallback_bbox: BoundingBox,
    fallback_crop: bytes,
) -> FieldCandidate:
    if not selections:
        return FieldCandidate(
            value=None,
            blocks=(),
            bbox=fallback_bbox,
            ocr_confidence=None,
            crop=fallback_crop,
            state=ExtractionState.MISSING,
        )

    unique_values: dict[str, str] = {}
    for selection in selections:
        value = selection.value.strip()
        if value:
            unique_values.setdefault(" ".join(value.split()), value)

    all_indices = sorted(_selection_indices(selections))
    if not unique_values or not all_indices:
        return FieldCandidate(
            value=None,
            blocks=(),
            bbox=fallback_bbox,
            ocr_confidence=None,
            crop=fallback_crop,
            state=ExtractionState.MISSING,
        )

    selected_lines = [lines[index] for index in all_indices]
    selected_blocks = tuple(member.block for line in selected_lines for member in line.members)
    bounds = _bounds_for_indices(lines, all_indices)
    character_count = sum(max(len(line.text), 1) for line in selected_lines)
    confidence = sum(line.confidence * max(len(line.text), 1) for line in selected_lines)
    confidence /= character_count
    alternatives = tuple(unique_values.values())
    state = ExtractionState.FOUND if len(alternatives) == 1 else ExtractionState.AMBIGUOUS
    return FieldCandidate(
        value=alternatives[0] if state is ExtractionState.FOUND else None,
        blocks=selected_blocks,
        bbox=_bbox_from_bounds(bounds),
        ocr_confidence=float(confidence),
        crop=_encode_crop(image, bounds),
        state=state,
        alternatives=() if state is ExtractionState.FOUND else alternatives,
    )


def extract_candidates(blocks: Sequence[TextBlock], image: np.ndarray) -> dict[str, FieldCandidate]:
    """Map OCR geometry to field candidates without consulting expected values."""

    _validate_image(image)
    lines = _group_lines(blocks, image.shape[1], image.shape[0])
    fallback_bounds = (0.0, 0.0, float(image.shape[1]), float(image.shape[0]))
    fallback_bbox = _bbox_from_bounds(fallback_bounds)
    fallback_crop = _encode_crop(image, fallback_bounds)

    selections: dict[str, list[_Selection]] = {}
    selections["government_warning"] = _warning_selections(lines)
    selections["alcohol_content"] = _alcohol_selections(lines)
    selections["net_contents"] = _net_content_selections(lines)
    selections["bottler"] = _bottler_selections(lines)
    selections["origin_country"] = _origin_selections(lines)

    assigned_indices = {
        index
        for field_name in (
            "government_warning",
            "alcohol_content",
            "net_contents",
            "bottler",
            "origin_country",
        )
        for index in _selection_indices(selections[field_name])
    }
    selections["class_type"] = _class_selections(lines, assigned_indices)
    assigned_indices.update(_selection_indices(selections["class_type"]))
    selections["brand_name"] = _brand_selections(lines, assigned_indices)

    return {
        field_name: _candidate_from_selections(
            selections[field_name], lines, image, fallback_bbox, fallback_crop
        )
        for field_name in FIELD_NAMES
    }
