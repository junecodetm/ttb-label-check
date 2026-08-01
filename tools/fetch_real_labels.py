"""Fetch real alcohol-label photographs from Open Food Facts for local OCR testing."""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from PIL import Image, UnidentifiedImageError

SEARCH_ENDPOINT = "https://world.openfoodfacts.org/api/v2/search"
USER_AGENT = "labelcheck-testing/1.0 (local OCR evaluation)"
DEFAULT_CATEGORIES = ("en:beers", "en:wines", "en:spirits")
COUNTRY_TAG = "en:united-states"
PAGE_SIZE = 50
REQUEST_DELAY_SECONDS = 0.25
RETRY_DELAY_SECONDS = 1.0
MAX_API_BYTES = 10 * 1024 * 1024
MAX_IMAGE_BYTES = 30 * 1024 * 1024
LICENSE = "CC BY-SA 3.0 (Open Food Facts)"
TRANSIENT_HTTP_STATUSES = frozenset({408, 425, 429, 500, 502, 503, 504})
SEARCH_FIELDS = (
    "code",
    "product_name",
    "brands",
    "generic_name",
    "categories_tags",
    "quantity",
    "product_quantity",
    "product_quantity_unit",
    "image_back_url",
    "image_front_url",
    "image_url",
    "selected_images",
    "nutriments",
)
MANIFEST_COLUMNS = (
    "filename",
    "brand_name",
    "class_type",
    "alcohol_content",
    "net_contents",
    "bottler",
    "origin_country",
)
CATEGORY_CLASS_TYPES = {
    "en:beers": "Beer",
    "en:wines": "Wine",
    "en:spirits": "Spirits",
}
VARIANT_PRIORITY = {
    "thumb": 1,
    "small": 2,
    "display": 3,
    "original": 4,
    "full": 4,
}


class _FetchError(RuntimeError):
    """Carry a concise network failure to the product-level skip logger."""


@dataclass(frozen=True, slots=True)
class _ImageCandidate:
    url: str
    kind: str
    score: tuple[int, int, int]


@dataclass(frozen=True, slots=True)
class _KeptProduct:
    filename: str
    ground_truth: dict[str, str]
    manifest_row: dict[str, str]
    used_back_image: bool


class _PoliteClient:
    """Serialize requests, throttle them, and retry one transient failure."""

    def __init__(self, timeout: float) -> None:
        self.timeout = timeout
        self._last_request_started: float | None = None

    def get(self, url: str, *, max_bytes: int) -> tuple[bytes, str]:
        """Return bounded response bytes and the final URL after redirects."""

        for attempt in range(2):
            self._wait_for_request_slot()
            request = Request(
                url,
                headers={"Accept": "*/*", "User-Agent": USER_AGENT},
            )
            try:
                with urlopen(request, timeout=self.timeout) as response:  # noqa: S310
                    data = response.read(max_bytes + 1)
                    if len(data) > max_bytes:
                        raise _FetchError(f"response exceeded {max_bytes // (1024 * 1024)} MiB")
                    if not data:
                        raise _FetchError("server returned an empty response")
                    return data, response.geturl()
            except HTTPError as error:
                transient = error.code in TRANSIENT_HTTP_STATUSES
                reason = f"HTTP {error.code}"
            except (OSError, URLError) as error:
                transient = True
                reason = str(error.reason) if isinstance(error, URLError) else str(error)
            except ValueError as error:
                transient = False
                reason = str(error)

            if attempt == 0 and transient:
                time.sleep(RETRY_DELAY_SECONDS)
                continue
            raise _FetchError(_one_line(reason)) from None

        raise _FetchError("request failed")

    def _wait_for_request_slot(self) -> None:
        if self._last_request_started is not None:
            elapsed = time.monotonic() - self._last_request_started
            time.sleep(max(0.0, REQUEST_DELAY_SECONDS - elapsed))
        self._last_request_started = time.monotonic()


def _one_line(value: object) -> str:
    return " ".join(str(value).split()) or "unknown error"


def _positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return number


def _positive_float(value: str) -> float:
    number = float(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("must be greater than 0")
    return number


def _parse_categories(value: str) -> tuple[str, ...]:
    categories = tuple(dict.fromkeys(item.strip() for item in value.split(",") if item.strip()))
    if not categories:
        raise argparse.ArgumentTypeError("must contain at least one category tag")
    return categories


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch a gitignored corpus of real alcohol-product label photographs."
    )
    parser.add_argument("--limit", type=_positive_int, default=30, help="total images to keep")
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(".real_labels"),
        help="corpus directory (default: .real_labels)",
    )
    parser.add_argument(
        "--categories",
        type=_parse_categories,
        default=DEFAULT_CATEGORIES,
        help="comma-separated Open Food Facts category tags",
    )
    parser.add_argument(
        "--timeout",
        type=_positive_float,
        default=20.0,
        help="per-request timeout in seconds",
    )
    return parser.parse_args(argv)


def _search_url(category: str, page: int) -> str:
    query = urlencode(
        {
            "categories_tags": category,
            "countries_tags": COUNTRY_TAG,
            "fields": ",".join(SEARCH_FIELDS),
            "page_size": PAGE_SIZE,
            "page": page,
        }
    )
    return f"{SEARCH_ENDPOINT}?{query}"


def _iter_products(client: _PoliteClient, category: str) -> Iterator[Mapping[str, object]]:
    page = 1
    while True:
        try:
            raw_payload, _source_url = client.get(
                _search_url(category, page),
                max_bytes=MAX_API_BYTES,
            )
            payload = json.loads(raw_payload)
        except (_FetchError, json.JSONDecodeError, UnicodeDecodeError) as error:
            _log_skip(f"{category} page {page}", f"search failed: {_one_line(error)}")
            return

        if not isinstance(payload, dict):
            _log_skip(f"{category} page {page}", "search returned a non-object payload")
            return
        products = payload.get("products")
        if not isinstance(products, list):
            _log_skip(f"{category} page {page}", "search response had no product list")
            return

        for index, product in enumerate(products, start=1):
            if isinstance(product, dict):
                yield product
            else:
                _log_skip(
                    f"{category} page {page} product {index}",
                    "search returned a malformed product",
                )

        total = payload.get("count")
        if not products or len(products) < PAGE_SIZE:
            return
        if isinstance(total, int) and page * PAGE_SIZE >= total:
            return
        page += 1


def _text(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, bool) or value is None:
        return ""
    if isinstance(value, (int, float)):
        return _format_number(value)
    return ""


def _format_number(value: int | float) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _extract_abv(product: Mapping[str, object]) -> str:
    nutriments = product.get("nutriments")
    sources: list[object] = [product.get("alcohol_value"), product.get("alcohol_100g")]
    if isinstance(nutriments, dict):
        sources.extend(
            (
                nutriments.get("alcohol_value"),
                nutriments.get("alcohol_100g"),
                nutriments.get("alcohol"),
            )
        )

    for value in sources:
        text = _text(value)
        match = re.search(r"\d+(?:[.,]\d+)?", text)
        if match is None:
            continue
        number = match.group(0).replace(",", ".")
        try:
            numeric_value = float(number)
        except ValueError:
            continue
        if 0.0 <= numeric_value <= 100.0:
            return f"{_format_number(numeric_value)}% ABV"
    return ""


def _extract_quantity(product: Mapping[str, object]) -> str:
    amount = _text(product.get("product_quantity"))
    unit = _text(product.get("product_quantity_unit")).casefold()
    if amount and unit:
        match = re.fullmatch(r"\d+(?:[.,]\d+)?", amount)
        if match is not None:
            numeric_value = float(match.group(0).replace(",", "."))
            if unit in {"ml", "millilitre", "millilitres", "milliliter", "milliliters"}:
                return f"{_format_number(numeric_value)} mL"
            if unit in {"cl", "centilitre", "centilitres", "centiliter", "centiliters"}:
                return f"{_format_number(numeric_value * 10)} mL"
            if unit in {"l", "litre", "litres", "liter", "liters"}:
                return f"{_format_number(numeric_value)} L"
            if unit in {"fl oz", "floz", "fluid ounce", "fluid ounces"}:
                return f"{_format_number(numeric_value)} fl oz"
    return _text(product.get("quantity"))


def _class_type(product: Mapping[str, object], category: str) -> str:
    generic_name = _text(product.get("generic_name"))
    return generic_name or CATEGORY_CLASS_TYPES.get(category, category.removeprefix("en:"))


def _walk_urls(value: object, path: tuple[str, ...] = ()) -> Iterator[tuple[str, tuple[str, ...]]]:
    if isinstance(value, str):
        if value.startswith(("https://", "http://")):
            yield value, path
        return
    if isinstance(value, dict):
        for key, nested_value in value.items():
            yield from _walk_urls(nested_value, (*path, str(key).casefold()))
    elif isinstance(value, list):
        for index, nested_value in enumerate(value):
            yield from _walk_urls(nested_value, (*path, str(index)))


def _variant_score(path: tuple[str, ...], url: str) -> tuple[int, int, int]:
    named_variant = max((VARIANT_PRIORITY.get(part, 0) for part in path), default=0)
    size_matches = re.findall(
        r"[._-](\d{2,5})(?:x\d{2,5})?(?=\.(?:jpe?g|png|webp)(?:\?|$))",
        url.casefold(),
    )
    pixels = max((int(value) for value in size_matches), default=0)
    english = int("en" in path)
    return named_variant, pixels, english


def _full_variant(url: str) -> str | None:
    full_url, replacements = re.subn(
        r"\.(?:100|200|400)\.(?=(?:jpe?g|png|webp)(?:\?|$))",
        ".full.",
        url,
        count=1,
        flags=re.IGNORECASE,
    )
    return full_url if replacements else None


def _image_candidates(product: Mapping[str, object]) -> tuple[_ImageCandidate, ...]:
    selected = product.get("selected_images")
    selected_images = selected if isinstance(selected, dict) else {}
    by_kind: dict[str, list[_ImageCandidate]] = {"back": [], "front": []}

    for kind in by_kind:
        for selected_kind, value in selected_images.items():
            normalized_kind = str(selected_kind).casefold()
            if normalized_kind != kind and not normalized_kind.startswith(f"{kind}_"):
                continue
            for url, path in _walk_urls(value, (normalized_kind,)):
                by_kind[kind].append(_ImageCandidate(url, kind, _variant_score(path, url)))

        for field_name, priority in (
            (f"image_{kind}_original_url", VARIANT_PRIORITY["original"]),
            (f"image_{kind}_url", VARIANT_PRIORITY["display"]),
        ):
            url = _text(product.get(field_name))
            if url.startswith(("https://", "http://")):
                score = _variant_score((field_name,), url)
                by_kind[kind].append(
                    _ImageCandidate(url, kind, (max(score[0], priority), score[1], score[2]))
                )

    generic_front_url = _text(product.get("image_url"))
    if generic_front_url.startswith(("https://", "http://")):
        score = _variant_score(("display",), generic_front_url)
        by_kind["front"].append(_ImageCandidate(generic_front_url, "front", score))

    ordered: list[_ImageCandidate] = []
    seen_urls: set[str] = set()
    for kind in ("back", "front"):
        candidates = sorted(by_kind[kind], key=lambda candidate: candidate.score, reverse=True)
        for candidate in candidates:
            full_url = _full_variant(candidate.url)
            if full_url is not None and full_url not in seen_urls:
                ordered.append(
                    _ImageCandidate(
                        full_url,
                        kind,
                        (VARIANT_PRIORITY["full"], candidate.score[1], candidate.score[2]),
                    )
                )
                seen_urls.add(full_url)
            if candidate.url not in seen_urls:
                ordered.append(candidate)
                seen_urls.add(candidate.url)
    return tuple(ordered)


def _jpeg_bytes(data: bytes) -> bytes:
    with Image.open(BytesIO(data)) as probe:
        probe.verify()

    with Image.open(BytesIO(data)) as image:
        image.load()
        if image.width < 1 or image.height < 1:
            raise ValueError("image has invalid dimensions")
        if image.format == "JPEG":
            return data
        converted = image.convert("RGB")
        output = BytesIO()
        converted.save(output, format="JPEG", quality=95)
        return output.getvalue()


def _product_code(product: Mapping[str, object]) -> str:
    code = _text(product.get("code"))
    return code if re.fullmatch(r"\d+", code) else ""


def _fetch_product(
    client: _PoliteClient,
    product: Mapping[str, object],
    category: str,
    images_directory: Path,
) -> _KeptProduct | None:
    code = _product_code(product)
    identity = code or _text(product.get("product_name")) or "unknown product"
    if not code:
        _log_skip(identity, "missing or unsafe product code")
        return None

    candidates = _image_candidates(product)
    if not candidates:
        _log_skip(code, "no usable back or front image URL")
        return None

    failures: list[str] = []
    for candidate in candidates:
        try:
            downloaded, source_url = client.get(candidate.url, max_bytes=MAX_IMAGE_BYTES)
            jpeg_data = _jpeg_bytes(downloaded)
        except (_FetchError, UnidentifiedImageError, OSError, SyntaxError, ValueError) as error:
            failures.append(f"{candidate.kind} image: {_one_line(error)}")
            continue

        filename = f"{code}.jpg"
        image_path = images_directory / filename
        try:
            image_path.write_bytes(jpeg_data)
        except OSError as error:
            image_path.unlink(missing_ok=True)
            _log_skip(code, f"could not write image: {_one_line(error)}")
            return None

        abv = _extract_abv(product)
        product_name = _text(product.get("product_name"))
        brands = _text(product.get("brands"))
        quantity = _extract_quantity(product)
        return _KeptProduct(
            filename=filename,
            ground_truth={
                "product_name": product_name,
                "brands": brands,
                "quantity": quantity,
                "abv_if_present": abv,
                "source_url": source_url,
                "license": LICENSE,
            },
            manifest_row={
                "filename": filename,
                "brand_name": brands,
                "class_type": _class_type(product, category),
                "alcohol_content": abv,
                "net_contents": quantity,
                "bottler": "",
                "origin_country": "",
            },
            used_back_image=candidate.kind == "back",
        )

    reason = failures[-1] if failures else "all image candidates failed"
    _log_skip(code, reason)
    return None


def _log_skip(identity: str, reason: str) -> None:
    print(f"skip {identity}: {_one_line(reason)}", file=sys.stderr)


def _write_metadata(out_directory: Path, products: Sequence[_KeptProduct]) -> None:
    ground_truth = {product.filename: product.ground_truth for product in products}
    ground_truth_path = out_directory / "ground_truth.json"
    ground_truth_path.write_text(
        json.dumps(ground_truth, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    manifest_path = out_directory / "manifest.csv"
    with manifest_path.open("w", encoding="utf-8", newline="") as manifest_file:
        writer = csv.DictWriter(
            manifest_file,
            fieldnames=MANIFEST_COLUMNS,
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(product.manifest_row for product in products)


def _fetch_corpus(
    *,
    limit: int,
    out_directory: Path,
    categories: Sequence[str],
    timeout: float,
) -> tuple[list[_KeptProduct], int, dict[str, int]]:
    images_directory = out_directory / "images"
    images_directory.mkdir(parents=True, exist_ok=True)

    client = _PoliteClient(timeout)
    streams: list[tuple[str, Iterator[Mapping[str, object]]]] = [
        (category, _iter_products(client, category)) for category in categories
    ]
    products: list[_KeptProduct] = []
    skipped = 0
    per_category = dict.fromkeys(categories, 0)
    seen_codes: set[str] = set()
    cursor = 0

    while streams and len(products) < limit:
        category, stream = streams[cursor]
        try:
            product = next(stream)
        except StopIteration:
            del streams[cursor]
            if streams:
                cursor %= len(streams)
            continue

        cursor = (cursor + 1) % len(streams)
        code = _product_code(product)
        if code and code in seen_codes:
            skipped += 1
            _log_skip(code, "duplicate product code")
            continue
        if code:
            seen_codes.add(code)

        try:
            kept_product = _fetch_product(client, product, category, images_directory)
        except Exception as error:  # Keep malformed third-party data scoped to one product.
            skipped += 1
            _log_skip(code or "unknown product", f"unexpected product error: {_one_line(error)}")
            continue
        if kept_product is None:
            skipped += 1
            continue

        products.append(kept_product)
        per_category[category] += 1

    _write_metadata(out_directory, products)
    return products, skipped, per_category


def main(argv: Sequence[str] | None = None) -> None:
    """Build the local corpus while keeping third-party failures isolated."""

    args = _parse_args(argv)
    products, skipped, per_category = _fetch_corpus(
        limit=args.limit,
        out_directory=args.out,
        categories=args.categories,
        timeout=args.timeout,
    )
    back_images = sum(product.used_back_image for product in products)
    category_summary = ", ".join(
        f"{category}={per_category[category]}" for category in args.categories
    )
    print(f"Summary: kept={len(products)} skipped={skipped}")
    print(f"Per-category: {category_summary}")
    print(f"Back-label images used: {back_images}")


if __name__ == "__main__":
    main()
