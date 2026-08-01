from __future__ import annotations

import io
import math
import random
from collections.abc import Iterable

from PIL import Image, ImageDraw, ImageFont

from labelcheck.config import GOVERNMENT_WARNING
from labelcheck.models import ApplicationRecord

FIXTURE_SEED = 20260731
LABEL_SIZE = (1400, 900)
LOW_RESOLUTION_SIZE = (700, 450)
BACKGROUND_COLOR = (244, 240, 229)
TEXT_COLOR = (18, 24, 33)


def sample_application_record() -> ApplicationRecord:
    """Keep the synthetic control and its expected record from drifting apart."""

    return ApplicationRecord(
        brand_name="OLD TOM DISTILLERY",
        class_type="Kentucky Straight Bourbon Whiskey",
        alcohol_content="45% Alc./Vol. (90 Proof)",
        net_contents="750 mL",
        bottler="Bottled by Old Tom Distillery, Bardstown, Kentucky",
    )


def _font(size: int) -> ImageFont.FreeTypeFont:
    """Use Pillow's embedded scalable font so fixtures do not depend on the host OS."""

    return ImageFont.load_default(size=size)


def _wrapped_lines(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    max_width: int,
) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current: list[str] = []
    for word in words:
        proposed = " ".join((*current, word))
        left, _top, right, _bottom = draw.textbbox((0, 0), proposed, font=font)
        if current and right - left > max_width:
            lines.append(" ".join(current))
            current = [word]
        else:
            current.append(word)
    if current:
        lines.append(" ".join(current))
    return lines


def _draw_centered(
    draw: ImageDraw.ImageDraw,
    y: int,
    text: str,
    font: ImageFont.FreeTypeFont,
    *,
    fill: tuple[int, int, int] = TEXT_COLOR,
    word_spacing: int = 12,
) -> None:
    words = text.split()
    widths = [draw.textlength(word, font=font) for word in words]
    line_width = sum(widths) + word_spacing * (len(words) - 1)
    x = (LABEL_SIZE[0] - line_width) / 2
    for word, width in zip(words, widths, strict=True):
        draw.text((x, y), word, font=font, fill=fill)
        x += width + word_spacing


def _draw_ornate_brand(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    rng: random.Random,
) -> None:
    """Simulate a script baseline without relying on an optional decorative font."""

    widths = [draw.textlength(character, font=font) for character in text]
    x = (LABEL_SIZE[0] - int(sum(widths))) / 2
    phase = rng.uniform(0.0, math.tau)
    for index, (character, width) in enumerate(zip(text, widths, strict=True)):
        y = 58 + int(8 * math.sin(phase + index * 0.55))
        draw.text((x, y), character, font=font, fill=TEXT_COLOR)
        x += width


def _draw_warning(
    draw: ImageDraw.ImageDraw,
    lines: Iterable[str],
    font: ImageFont.FreeTypeFont,
) -> None:
    y = 535
    for line in lines:
        draw.text((75, y), line, font=font, fill=TEXT_COLOR)
        y += 42


def make_label(
    *,
    ornate: bool = False,
    rotation_degrees: float = 0.0,
    glare: bool = False,
    low_resolution: bool = False,
    seed: int = FIXTURE_SEED,
    record: ApplicationRecord | None = None,
    warning_text: str | None = None,
) -> bytes:
    """Render deterministic label variants without committing binary fixtures.

    `record` and `warning_text` exist so a caller can render a deliberately
    non-compliant label, such as the title-case warning Jenny Park rejected.
    """

    rng = random.Random(seed)
    record = record or sample_application_record()
    image = Image.new("RGB", LABEL_SIZE, BACKGROUND_COLOR)
    draw = ImageDraw.Draw(image)

    brand_font = _font(60)
    if ornate:
        _draw_ornate_brand(draw, record.brand_name, brand_font, rng)
    else:
        _draw_centered(draw, 58, record.brand_name, brand_font, word_spacing=50)

    _draw_centered(draw, 170, record.class_type, _font(36), word_spacing=50)
    _draw_centered(draw, 250, record.alcohol_content, _font(34), word_spacing=50)
    _draw_centered(draw, 325, record.net_contents, _font(34), word_spacing=50)
    _draw_centered(draw, 415, record.bottler, _font(28))

    warning_font = _font(27)
    warning_lines = _wrapped_lines(
        draw, warning_text or GOVERNMENT_WARNING, warning_font, max_width=1250
    )
    _draw_warning(draw, warning_lines, warning_font)

    if glare:
        overlay = Image.new("RGBA", LABEL_SIZE, (255, 255, 255, 0))
        glare_draw = ImageDraw.Draw(overlay)
        center_x = rng.randint(820, 1040)
        center_y = rng.randint(245, 390)
        glare_draw.ellipse(
            (center_x - 230, center_y - 100, center_x + 230, center_y + 100),
            fill=(255, 255, 255, 180),
        )
        image = Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")

    if rotation_degrees:
        image = image.rotate(
            rotation_degrees,
            resample=Image.Resampling.BICUBIC,
            expand=False,
            fillcolor=BACKGROUND_COLOR,
        )

    if low_resolution:
        image = image.resize(LOW_RESOLUTION_SIZE, Image.Resampling.LANCZOS)

    output = io.BytesIO()
    image.save(output, format="PNG", compress_level=9, optimize=False)
    return output.getvalue()
