import csv
import io

import numpy as np
import pytest
from PIL import Image

from labelcheck import preprocess as preprocess_module
from labelcheck.batch import MANIFEST_COLUMNS, ManifestError, parse_manifest
from labelcheck.preprocess import preprocess_image


def _image_bytes(image: Image.Image, format_name: str, **save_options: object) -> bytes:
    output = io.BytesIO()
    image.save(output, format=format_name, **save_options)
    return output.getvalue()


def _truncated_png_bytes() -> bytes:
    encoded = _image_bytes(Image.new("RGB", (16, 16), "white"), "PNG")
    truncated = encoded[: len(encoded) // 2]
    assert truncated.startswith(b"\x89PNG\r\n\x1a\n")
    return truncated


def _decoded_bgr(image_bytes: bytes) -> np.ndarray:
    decoded = preprocess_image(image_bytes)

    assert isinstance(decoded, np.ndarray)
    assert decoded.dtype == np.uint8
    assert decoded.ndim == 3
    assert decoded.shape[0] > 0
    assert decoded.shape[1] > 0
    assert decoded.shape[2] == 3
    assert decoded.flags.c_contiguous
    return decoded


def _manifest_row(
    filename: str = "label.png",
    *,
    brand_name: str = "Stone's Throw",
    bottler: str = "Acme Bottling Co.",
) -> tuple[str, ...]:
    return (
        filename,
        brand_name,
        "Whiskey",
        "45% Alc./Vol. (90 Proof)",
        "750 mL",
        bottler,
        "",
    )


def _manifest_bytes(
    rows: list[tuple[str, ...]],
    *,
    header: tuple[str, ...] = MANIFEST_COLUMNS,
    encoding: str = "utf-8",
    lineterminator: str = "\n",
) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator=lineterminator)
    writer.writerow(header)
    writer.writerows(rows)
    return output.getvalue().encode(encoding)


@pytest.mark.parametrize(
    ("payload", "expected_message"),
    (
        pytest.param(
            b"",
            "image_bytes must contain an encoded image",
            id="zero-byte-upload",
        ),
        pytest.param(
            bytes(range(256)),
            "image_bytes could not be decoded",
            id="random-non-image-bytes",
        ),
        pytest.param(
            b"%PDF-1.7\n% renamed as label.png\n%%EOF\n",
            "image_bytes could not be decoded",
            id="pdf-renamed-as-png",
        ),
        pytest.param(
            _truncated_png_bytes(),
            "image_bytes could not be decoded",
            id="truncated-png",
        ),
    ),
)
def test_invalid_image_uploads_raise_clean_value_error(
    payload: bytes,
    expected_message: str,
) -> None:
    with pytest.raises(ValueError) as captured:
        preprocess_image(payload)

    assert type(captured.value) is ValueError
    assert str(captured.value) == expected_message


def test_16_bit_png_decodes_to_uint8_bgr() -> None:
    values = np.full((736, 736), 32768, dtype=np.uint16)
    values[:, 368:] = np.iinfo(np.uint16).max
    source = Image.fromarray(values)
    assert source.mode == "I;16"
    payload = _image_bytes(source, "PNG")

    with Image.open(io.BytesIO(payload)) as reopened:
        assert reopened.mode == "I;16"
        assert reopened.getpixel((100, 100)) == 32768
        assert reopened.getpixel((600, 100)) == 65535

    decoded = _decoded_bgr(payload)

    # NOTE: current behavior, looks like a bug because distinct 16-bit midrange
    # and maximum values are both silently clipped to white during RGB conversion.
    assert np.all(decoded == 255)


def test_cmyk_jpeg_decodes_with_distinct_bgr_colors() -> None:
    source = Image.new("CMYK", (736, 736), (0, 255, 255, 0))
    source.paste((255, 0, 0, 0), (368, 0, 736, 736))
    payload = _image_bytes(source, "JPEG", quality=100, subsampling=0)

    decoded = _decoded_bgr(payload)
    red = decoded[100, 100]
    cyan = decoded[100, 600]

    assert red[2] > red[1] and red[2] > red[0]
    assert cyan[0] > cyan[2] and cyan[1] > cyan[2]


@pytest.mark.parametrize(("mode", "white_value"), (("L", 255), ("1", 1)))
def test_grayscale_png_modes_decode_to_three_equal_bgr_channels(
    mode: str,
    white_value: int,
) -> None:
    source = Image.new(mode, (736, 736), 0)
    source.paste(white_value, (368, 0, 736, 736))

    decoded = _decoded_bgr(_image_bytes(source, "PNG"))
    dark = decoded[100, 100]
    light = decoded[100, 600]

    assert dark[0] == dark[1] == dark[2]
    assert light[0] == light[1] == light[2]
    assert light[0] > dark[0]


def test_palette_png_transparency_is_composited_over_white() -> None:
    source = Image.new("P", (736, 736), 0)
    source.putpalette([0, 0, 255, 255, 0, 0] + [0, 0, 0] * 254)
    source.paste(1, (368, 0, 736, 736))
    payload = _image_bytes(source, "PNG", transparency=0)

    with Image.open(io.BytesIO(payload)) as reopened:
        assert reopened.mode == "P"
        assert reopened.info["transparency"] == 0

    decoded = _decoded_bgr(payload)
    transparent = decoded[100, 100]
    opaque_red = decoded[100, 600]

    assert transparent.tolist() == [255, 255, 255]
    assert opaque_red[2] > opaque_red[1] and opaque_red[2] > opaque_red[0]


def test_animated_gif_decodes_its_first_frame() -> None:
    first = Image.new("RGB", (20, 12), (255, 0, 0))
    second = Image.new("RGB", first.size, (0, 255, 0))
    payload = _image_bytes(
        first,
        "GIF",
        save_all=True,
        append_images=[second],
        duration=100,
        loop=0,
    )

    with Image.open(io.BytesIO(payload)) as reopened:
        assert reopened.is_animated
        assert reopened.n_frames == 2

    decoded = _decoded_bgr(payload)
    pixel = decoded[decoded.shape[0] // 2, decoded.shape[1] // 2]

    assert pixel[2] > pixel[1] and pixel[2] > pixel[0]


def test_exif_oriented_jpeg_decodes_without_crashing() -> None:
    source = Image.new("RGB", (900, 736), "white")
    exif = Image.Exif()
    exif[274] = 6

    _decoded_bgr(_image_bytes(source, "JPEG", exif=exif))


def test_extreme_aspect_ratio_image_decodes_with_nonempty_dimensions() -> None:
    source = Image.new("RGB", (4000, 10), "white")

    decoded = _decoded_bgr(_image_bytes(source, "PNG"))

    assert decoded.shape == (4, 1400, 3)


def test_one_pixel_image_decodes_without_crashing() -> None:
    source = Image.new("RGB", (1, 1), (10, 20, 30))

    decoded = _decoded_bgr(_image_bytes(source, "PNG"))

    assert decoded.shape == (2, 2, 3)
    # NOTE: current behavior, looks like a bug because CLAHE silently changes the
    # sole dark BGR pixel from [30, 20, 10] to nearly white before upscaling it.
    assert np.all(decoded == np.array([255, 255, 247], dtype=np.uint8))


def test_manifest_with_utf8_bom_parses() -> None:
    payload = b"\xef\xbb\xbf" + _manifest_bytes([_manifest_row()])

    rows = parse_manifest(payload)

    assert len(rows) == 1
    assert rows[0].filename == "label.png"
    assert rows[0].application.brand_name == "Stone's Throw"


def test_windows_1252_manifest_with_accented_name_parses() -> None:
    payload = _manifest_bytes(
        [_manifest_row(brand_name="Château Reserve")],
        encoding="cp1252",
    )

    rows = parse_manifest(payload)

    assert rows[0].application.brand_name == "Château Reserve"


def test_manifest_with_crlf_line_endings_parses() -> None:
    payload = _manifest_bytes([_manifest_row()], lineterminator="\r\n")
    assert payload.count(b"\r\n") == 2

    rows = parse_manifest(payload)

    assert rows[0].filename == "label.png"


def test_manifest_header_allows_surrounding_whitespace() -> None:
    padded_header = tuple(f"  {column}  " for column in MANIFEST_COLUMNS)
    payload = _manifest_bytes([_manifest_row()], header=padded_header)

    rows = parse_manifest(payload)

    assert rows[0].application.bottler == "Acme Bottling Co."


def test_manifest_preserves_ten_thousand_character_field() -> None:
    long_value = "X" * 10_000
    payload = _manifest_bytes([_manifest_row(brand_name=long_value)])

    rows = parse_manifest(payload)

    assert rows[0].application.brand_name == long_value


def test_manifest_rejects_duplicate_filename_that_differs_only_by_case() -> None:
    payload = _manifest_bytes(
        [
            _manifest_row("Label.PNG"),
            _manifest_row("label.png", brand_name="Second Brand"),
        ]
    )

    with pytest.raises(ManifestError) as captured:
        parse_manifest(payload)

    assert type(captured.value) is ManifestError
    assert str(captured.value) == (
        "Row 3 repeats filename 'label.png'. "
        "Filenames must be unique even when letter case differs."
    )


def test_iphone_heic_photo_decodes_when_the_optional_wheel_is_present() -> None:
    """HEIC is the default iPhone camera format, so agents will upload it."""

    pillow_heif = pytest.importorskip("pillow_heif")
    assert preprocess_module.HEIF_SUPPORTED

    buffer = io.BytesIO()
    Image.new("RGB", (64, 48), (200, 120, 60)).save(buffer, format="HEIF")

    decoded = preprocess_image(buffer.getvalue())

    # Dimensions are not asserted exactly: a 64x48 image is below the OCR target, so
    # preprocessing upscales it. What matters is that it decoded and kept its shape.
    height, width = decoded.shape[:2]
    assert decoded.shape[2] == 3
    assert width > height
    assert round(width / height, 2) == round(64 / 48, 2)
    assert pillow_heif is not None


def test_heic_support_is_reported_not_assumed() -> None:
    """A host without the wheel must still import; the flag says which world we are in."""

    assert isinstance(preprocess_module.HEIF_SUPPORTED, bool)
