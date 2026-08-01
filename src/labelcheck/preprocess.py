from __future__ import annotations

import io
import math
from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

from labelcheck.config import (
    BLUR_VARIANCE_THRESHOLD,
    CLAHE_CLIP_LIMIT,
    CLAHE_TILE_GRID_SIZE,
    CONTRAST_HIGH_PERCENTILE,
    CONTRAST_LOW_PERCENTILE,
    GLARE_LUMINANCE_THRESHOLD,
    HOUGH_CANNY_HIGH_THRESHOLD,
    HOUGH_CANNY_LOW_THRESHOLD,
    HOUGH_MAX_LINE_GAP_RATIO,
    HOUGH_MIN_LINE_LENGTH_PX,
    HOUGH_MIN_LINE_LENGTH_RATIO,
    ILLUMINATION_TILE_COLUMNS,
    ILLUMINATION_TILE_ROWS,
    MAX_DESKEW_ANGLE_DEGREES,
    MAX_GLARE_FRACTION,
    MAX_TILE_ILLUMINATION_SPREAD,
    MIN_CONTRAST_RANGE,
    MIN_DESKEW_ANGLE_DEGREES,
    MIN_DESKEW_SUPPORTING_LINES,
    MIN_GLARE_FRACTION,
    OCR_MAX_SIDE_PX,
    OCR_MAX_UPSCALE_FACTOR,
    OCR_TARGET_MIN_SIDE_PX,
    PERSPECTIVE_APPROXIMATION_RATIO,
    PERSPECTIVE_BORDER_MARGIN_RATIO,
    PERSPECTIVE_CORNER_COSINE,
    PERSPECTIVE_MAX_AREA_RATIO,
    PERSPECTIVE_MAX_OUTPUT_AREA_RATIO,
    PERSPECTIVE_MIN_AREA_RATIO,
    PERSPECTIVE_MIN_OUTPUT_SIDE_PX,
    PERSPECTIVE_OPPOSITE_SIDE_DELTA,
    QUALITY_ANALYSIS_MAX_SIDE_PX,
)


@dataclass(frozen=True, slots=True)
class ImageQuality:
    """Expose why a corrective stage ran so preprocessing remains auditable."""

    width: int
    height: int
    blur_variance: float
    contrast_range: float
    skew_angle_degrees: float
    illumination_spread: float
    glare_fraction: float
    is_blurry: bool
    needs_deskew: bool
    needs_perspective_correction: bool
    needs_clahe: bool
    needs_downscale: bool
    needs_upscale: bool

    @property
    def needs_processing(self) -> bool:
        """Let callers distinguish the clean decode-only path without repeating gates."""

        return any(
            (
                self.needs_deskew,
                self.needs_perspective_correction,
                self.needs_clahe,
                self.needs_downscale,
                self.needs_upscale,
            )
        )


def _validate_bgr_image(image: np.ndarray) -> None:
    if (
        not isinstance(image, np.ndarray)
        or image.dtype != np.uint8
        or image.ndim != 3
        or image.shape[2] != 3
        or image.shape[0] == 0
        or image.shape[1] == 0
    ):
        raise ValueError("image must be a non-empty uint8 BGR array")


def _decode_with_exif(image_bytes: bytes) -> np.ndarray:
    if not isinstance(image_bytes, bytes) or not image_bytes:
        raise ValueError("image_bytes must contain an encoded image")

    try:
        with Image.open(io.BytesIO(image_bytes)) as source:
            oriented = ImageOps.exif_transpose(source)
            if oriented.mode in {"RGBA", "LA"} or "transparency" in oriented.info:
                foreground = oriented.convert("RGBA")
                background = Image.new("RGBA", foreground.size, (255, 255, 255, 255))
                background.alpha_composite(foreground)
                rgb = background.convert("RGB")
            else:
                rgb = oriented.convert("RGB")
            rgb_array = np.array(rgb, dtype=np.uint8, copy=True)
    except (UnidentifiedImageError, OSError, ValueError) as error:
        raise ValueError("image_bytes could not be decoded") from error

    return np.ascontiguousarray(cv2.cvtColor(rgb_array, cv2.COLOR_RGB2BGR))


def _analysis_frame(image: np.ndarray) -> np.ndarray:
    height, width = image.shape[:2]
    longest_side = max(height, width)
    if longest_side <= QUALITY_ANALYSIS_MAX_SIDE_PX:
        return image
    scale = QUALITY_ANALYSIS_MAX_SIDE_PX / longest_side
    return cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)


def _weighted_median(values: np.ndarray, weights: np.ndarray) -> float:
    order = np.argsort(values)
    sorted_values = values[order]
    cumulative = np.cumsum(weights[order])
    midpoint = cumulative[-1] / 2.0
    return float(sorted_values[int(np.searchsorted(cumulative, midpoint, side="left"))])


def _estimate_skew(gray: np.ndarray) -> float:
    edges = cv2.Canny(gray, HOUGH_CANNY_LOW_THRESHOLD, HOUGH_CANNY_HIGH_THRESHOLD)
    height, width = gray.shape
    minimum_length = max(HOUGH_MIN_LINE_LENGTH_PX, int(width * HOUGH_MIN_LINE_LENGTH_RATIO))
    maximum_gap = max(1, int(width * HOUGH_MAX_LINE_GAP_RATIO))
    lines = cv2.HoughLinesP(
        edges,
        1,
        np.pi / 180.0,
        threshold=minimum_length,
        minLineLength=minimum_length,
        maxLineGap=maximum_gap,
    )
    if lines is None:
        return 0.0

    angles: list[float] = []
    lengths: list[float] = []
    for x1, y1, x2, y2 in lines.reshape(-1, 4):
        delta_x = float(x2 - x1)
        delta_y = float(y2 - y1)
        angle = math.degrees(math.atan2(delta_y, delta_x))
        while angle <= -90.0:
            angle += 180.0
        while angle > 90.0:
            angle -= 180.0
        if abs(angle) <= MAX_DESKEW_ANGLE_DEGREES:
            angles.append(angle)
            lengths.append(math.hypot(delta_x, delta_y))

    if len(angles) < MIN_DESKEW_SUPPORTING_LINES:
        return 0.0
    return _weighted_median(np.asarray(angles), np.asarray(lengths))


def _tile_illumination_spread(gray: np.ndarray) -> float:
    tiles: list[float] = []
    for row in np.array_split(gray, ILLUMINATION_TILE_ROWS, axis=0):
        for tile in np.array_split(row, ILLUMINATION_TILE_COLUMNS, axis=1):
            if tile.size:
                tiles.append(float(np.median(tile)))
    return max(tiles) - min(tiles) if tiles else 0.0


def _ordered_quad(points: np.ndarray) -> np.ndarray:
    centroid = points.mean(axis=0)
    angles = np.arctan2(points[:, 1] - centroid[1], points[:, 0] - centroid[0])
    ordered = points[np.argsort(angles)]
    top_left_index = int(np.argmin(ordered[:, 0] + ordered[:, 1]))
    return np.roll(ordered, -top_left_index, axis=0).astype(np.float32)


def _edge_length(first: np.ndarray, second: np.ndarray) -> float:
    return float(np.linalg.norm(first - second))


def _relative_difference(first: float, second: float) -> float:
    denominator = max(first, second)
    return abs(first - second) / denominator if denominator else 0.0


def _maximum_corner_cosine(points: np.ndarray) -> float:
    cosines: list[float] = []
    for index in range(4):
        previous = points[(index - 1) % 4] - points[index]
        following = points[(index + 1) % 4] - points[index]
        denominator = float(np.linalg.norm(previous) * np.linalg.norm(following))
        if denominator:
            cosines.append(abs(float(np.dot(previous, following))) / denominator)
    return max(cosines, default=0.0)


def _quad_is_distorted(points: np.ndarray) -> bool:
    top = _edge_length(points[0], points[1])
    right = _edge_length(points[1], points[2])
    bottom = _edge_length(points[2], points[3])
    left = _edge_length(points[3], points[0])
    opposite_delta = max(_relative_difference(top, bottom), _relative_difference(left, right))
    return (
        opposite_delta > PERSPECTIVE_OPPOSITE_SIDE_DELTA
        or _maximum_corner_cosine(points) > PERSPECTIVE_CORNER_COSINE
    )


def _touches_frame_border(points: np.ndarray, width: int, height: int) -> bool:
    margin_x = width * PERSPECTIVE_BORDER_MARGIN_RATIO
    margin_y = height * PERSPECTIVE_BORDER_MARGIN_RATIO
    near_left = np.any(points[:, 0] <= margin_x)
    near_right = np.any(points[:, 0] >= width - 1 - margin_x)
    near_top = np.any(points[:, 1] <= margin_y)
    near_bottom = np.any(points[:, 1] >= height - 1 - margin_y)
    return bool(near_left and near_right and near_top and near_bottom)


def _find_largest_perspective_quad(image: np.ndarray) -> np.ndarray | None:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blurred, HOUGH_CANNY_LOW_THRESHOLD, HOUGH_CANNY_HIGH_THRESHOLD)
    contours, _hierarchy = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    image_area = float(image.shape[0] * image.shape[1])

    for contour in sorted(contours, key=cv2.contourArea, reverse=True):
        area_ratio = cv2.contourArea(contour) / image_area
        if area_ratio < PERSPECTIVE_MIN_AREA_RATIO:
            break
        if area_ratio > PERSPECTIVE_MAX_AREA_RATIO:
            continue
        perimeter = cv2.arcLength(contour, True)
        approximation = cv2.approxPolyDP(contour, PERSPECTIVE_APPROXIMATION_RATIO * perimeter, True)
        if len(approximation) != 4 or not cv2.isContourConvex(approximation):
            continue
        ordered = _ordered_quad(approximation.reshape(4, 2).astype(np.float32))
        if _touches_frame_border(ordered, image.shape[1], image.shape[0]):
            continue
        if _quad_is_distorted(ordered):
            return ordered
    return None


def assess_image_quality(image: np.ndarray) -> ImageQuality:
    """Measure cheap signals once so clean images avoid corrective transformations."""

    _validate_bgr_image(image)
    analysis = _analysis_frame(image)
    gray = cv2.cvtColor(analysis, cv2.COLOR_BGR2GRAY)
    blur_variance = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    low, high = np.percentile(gray, [CONTRAST_LOW_PERCENTILE, CONTRAST_HIGH_PERCENTILE])
    contrast_range = float(high - low)
    skew_angle = _estimate_skew(gray)
    illumination_spread = _tile_illumination_spread(gray)
    glare_fraction = float(np.mean(gray >= GLARE_LUMINANCE_THRESHOLD))
    perspective_quad = _find_largest_perspective_quad(analysis)
    minimum_side = min(image.shape[:2])

    glare_detected = MIN_GLARE_FRACTION <= glare_fraction <= MAX_GLARE_FRACTION
    needs_clahe = (
        contrast_range < MIN_CONTRAST_RANGE
        or illumination_spread > MAX_TILE_ILLUMINATION_SPREAD
        or glare_detected
    )
    return ImageQuality(
        width=image.shape[1],
        height=image.shape[0],
        blur_variance=blur_variance,
        contrast_range=contrast_range,
        skew_angle_degrees=skew_angle,
        illumination_spread=illumination_spread,
        glare_fraction=glare_fraction,
        is_blurry=blur_variance < BLUR_VARIANCE_THRESHOLD,
        needs_deskew=MIN_DESKEW_ANGLE_DEGREES <= abs(skew_angle) <= MAX_DESKEW_ANGLE_DEGREES,
        needs_perspective_correction=perspective_quad is not None,
        needs_clahe=needs_clahe,
        needs_downscale=max(image.shape[:2]) > OCR_MAX_SIDE_PX,
        needs_upscale=minimum_side < OCR_TARGET_MIN_SIDE_PX,
    )


def _deskew(image: np.ndarray, angle_degrees: float) -> np.ndarray:
    height, width = image.shape[:2]
    center = (width / 2.0, height / 2.0)
    matrix = cv2.getRotationMatrix2D(center, angle_degrees, 1.0)
    return cv2.warpAffine(
        image,
        matrix,
        (width, height),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(255, 255, 255),
    )


def _correct_perspective(image: np.ndarray, points: np.ndarray) -> np.ndarray:
    top_left, top_right, bottom_right, bottom_left = points
    width = int(
        round(
            max(
                _edge_length(top_left, top_right),
                _edge_length(bottom_left, bottom_right),
            )
        )
    )
    height = int(
        round(
            max(
                _edge_length(top_left, bottom_left),
                _edge_length(top_right, bottom_right),
            )
        )
    )
    if min(width, height) < PERSPECTIVE_MIN_OUTPUT_SIDE_PX:
        raise ValueError("perspective quadrilateral is too small")
    if width * height > image.shape[0] * image.shape[1] * PERSPECTIVE_MAX_OUTPUT_AREA_RATIO:
        raise ValueError("perspective quadrilateral would create an excessive frame")

    destination = np.asarray(
        ((0.0, 0.0), (width - 1.0, 0.0), (width - 1.0, height - 1.0), (0.0, height - 1.0)),
        dtype=np.float32,
    )
    matrix = cv2.getPerspectiveTransform(points.astype(np.float32), destination)
    return cv2.warpPerspective(image, matrix, (width, height), flags=cv2.INTER_CUBIC)


def _apply_clahe(image: np.ndarray) -> np.ndarray:
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
    luminance, channel_a, channel_b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=CLAHE_CLIP_LIMIT, tileGridSize=CLAHE_TILE_GRID_SIZE)
    enhanced = cv2.merge((clahe.apply(luminance), channel_a, channel_b))
    return cv2.cvtColor(enhanced, cv2.COLOR_LAB2BGR)


def _upscale_if_needed(image: np.ndarray) -> np.ndarray:
    minimum_side = min(image.shape[:2])
    if minimum_side >= OCR_TARGET_MIN_SIDE_PX:
        return image
    scale = min(
        OCR_TARGET_MIN_SIDE_PX / minimum_side,
        OCR_MAX_UPSCALE_FACTOR,
        OCR_MAX_SIDE_PX / max(image.shape[:2]),
    )
    if scale <= 1.0:
        return image
    width = int(round(image.shape[1] * scale))
    height = int(round(image.shape[0] * scale))
    return cv2.resize(image, (width, height), interpolation=cv2.INTER_CUBIC)


def _downscale_if_needed(image: np.ndarray) -> np.ndarray:
    longest_side = max(image.shape[:2])
    if longest_side <= OCR_MAX_SIDE_PX:
        return image
    scale = OCR_MAX_SIDE_PX / longest_side
    width = int(round(image.shape[1] * scale))
    height = int(round(image.shape[0] * scale))
    return cv2.resize(image, (width, height), interpolation=cv2.INTER_AREA)


def preprocess_image(image_bytes: bytes) -> np.ndarray:
    """Correct only measured defects and retain the last usable frame on transform failure."""

    current = _decode_with_exif(image_bytes)
    quality = assess_image_quality(current)

    if not any(
        (
            quality.needs_downscale,
            quality.needs_deskew,
            quality.needs_perspective_correction,
            quality.needs_clahe,
            quality.needs_upscale,
        )
    ):
        return np.ascontiguousarray(current, dtype=np.uint8)

    if quality.needs_downscale:
        try:
            current = _downscale_if_needed(current)
        except (cv2.error, ValueError, FloatingPointError):
            pass

    if quality.needs_deskew:
        try:
            current = _deskew(current, quality.skew_angle_degrees)
        except (cv2.error, ValueError, FloatingPointError):
            pass

    if quality.needs_perspective_correction or quality.needs_deskew:
        try:
            quadrilateral = _find_largest_perspective_quad(current)
            if quadrilateral is not None:
                current = _correct_perspective(current, quadrilateral)
        except (cv2.error, ValueError, FloatingPointError):
            pass

    if quality.needs_clahe:
        try:
            current = _apply_clahe(current)
        except (cv2.error, ValueError, FloatingPointError):
            pass

    try:
        current = _downscale_if_needed(current)
        current = _upscale_if_needed(current)
    except (cv2.error, ValueError, FloatingPointError):
        pass

    return np.ascontiguousarray(current, dtype=np.uint8)
