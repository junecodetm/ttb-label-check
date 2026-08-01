"""Fetch approved alcohol labels and registry ground truth from TTB COLAs Online."""

from __future__ import annotations

import argparse
import csv
import http.cookiejar
import json
import re
import sys
import time
import warnings
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from html.parser import HTMLParser
from http.client import HTTPException
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urljoin, urlparse
from urllib.request import HTTPCookieProcessor, Request, build_opener

from PIL import Image, UnidentifiedImageError

BASE_URL = "https://ttbonline.gov/colasonline/"
SEARCH_PAGE_URL = urljoin(BASE_URL, "publicSearchColasBasic.do")
SEARCH_RESULTS_URL = urljoin(
    BASE_URL,
    "publicSearchColasBasicProcess.do?action=search",
)
DETAIL_URL = urljoin(BASE_URL, "viewColaDetails.do")
DEFAULT_PRODUCT = "%WHISKEY%"
DEFAULT_DELAY_SECONDS = 1.0
REQUEST_TIMEOUT_SECONDS = 30.0
MAX_HTML_BYTES = 10 * 1024 * 1024
MAX_IMAGE_BYTES = 40 * 1024 * 1024
MAX_IMAGE_PIXELS = 40_000_000
TRANSIENT_HTTP_STATUSES = frozenset({408, 425, 429, 500, 502, 503, 504})
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
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
DETAIL_LABELS = (
    "TTB ID:",
    "Status:",
    "Vendor Code:",
    "Serial #:",
    "Class/Type Code:",
    "Origin Code:",
    "Brand Name:",
    "Fanciful Name:",
    "Type of Application:",
    "For Sale In:",
    "Total Bottle Capacity:",
    "Wine Vintage:",
    "Formula:",
    "Approval Date:",
    "Qualifications:",
    "Plant Registry/Basic Permit/Brewers No (Principal Place of Business):",
    "Plant Registry/Basic Permit/Brewers No (Other):",
    "Contact Information:",
)
PLANT_LABEL = "Plant Registry/Basic Permit/Brewers No (Principal Place of Business):"
PLANT_STOP_LABELS = (
    "Plant Registry/Basic Permit/Brewers No (Other):",
    "Contact Information:",
)
DOMESTIC_ORIGINS = frozenset(
    {
        "ALABAMA",
        "ALASKA",
        "AMERICAN SAMOA",
        "ARIZONA",
        "ARKANSAS",
        "CALIFORNIA",
        "COLORADO",
        "CONNECTICUT",
        "DELAWARE",
        "DISTRICT OF COLUMBIA",
        "FLORIDA",
        "GEORGIA",
        "GUAM",
        "HAWAII",
        "IDAHO",
        "ILLINOIS",
        "INDIANA",
        "IOWA",
        "KANSAS",
        "KENTUCKY",
        "LOUISIANA",
        "MAINE",
        "MARYLAND",
        "MASSACHUSETTS",
        "MICHIGAN",
        "MINNESOTA",
        "MISSISSIPPI",
        "MISSOURI",
        "MONTANA",
        "NEBRASKA",
        "NEVADA",
        "NEW HAMPSHIRE",
        "NEW JERSEY",
        "NEW MEXICO",
        "NEW YORK",
        "NORTH CAROLINA",
        "NORTH DAKOTA",
        "NORTHERN MARIANA ISLANDS",
        "OHIO",
        "OKLAHOMA",
        "OREGON",
        "PENNSYLVANIA",
        "PUERTO RICO",
        "RHODE ISLAND",
        "SOUTH CAROLINA",
        "SOUTH DAKOTA",
        "TENNESSEE",
        "TEXAS",
        "UNITED STATES",
        "UNITED STATES OF AMERICA",
        "US VIRGIN ISLANDS",
        "UTAH",
        "VERMONT",
        "VIRGIN ISLANDS",
        "VIRGINIA",
        "WASHINGTON",
        "WEST VIRGINIA",
        "WISCONSIN",
        "WYOMING",
    }
)


class _FetchError(RuntimeError):
    """Carry a concise request failure to the record-level skip logger."""


class _SearchError(RuntimeError):
    """Identify a search-page or search-results contract failure."""


@dataclass(frozen=True, slots=True)
class _Response:
    body: bytes
    content_type: str
    final_url: str


@dataclass(frozen=True, slots=True)
class _FormControl:
    name: str
    value: str
    kind: str


@dataclass(frozen=True, slots=True)
class _SearchForm:
    method: str
    action: str
    controls: tuple[_FormControl, ...]


@dataclass(frozen=True, slots=True)
class _RegistryRecord:
    ttbid: str
    brand_name: str
    fanciful_name: str
    class_type: str
    origin_code: str
    origin_country: str
    bottler: str
    source_url: str


@dataclass(frozen=True, slots=True)
class _KeptImage:
    filename: str
    width: int
    height: int
    ground_truth: dict[str, str]
    manifest_row: dict[str, str]


@dataclass(slots=True)
class _RunStats:
    skipped: int = 0

    def skip(self, identity: str, reason: object) -> None:
        self.skipped += 1
        print(f"skip {identity}: {_one_line(reason)}", file=sys.stderr)


class _PoliteClient:
    """Keep one cookie-aware opener while serializing and throttling requests."""

    def __init__(self, delay: float) -> None:
        self.delay = delay
        self.cookie_jar = http.cookiejar.CookieJar()
        self.opener = build_opener(HTTPCookieProcessor(self.cookie_jar))
        self._last_request_started: float | None = None

    def get(self, url: str, *, max_bytes: int) -> _Response:
        """Fetch one bounded response with the shared COLAs Online session."""

        return self._request(url, data=None, max_bytes=max_bytes)

    def post(self, url: str, fields: Sequence[tuple[str, str]]) -> _Response:
        """Submit form fields through the shared COLAs Online session."""

        data = urlencode(fields).encode("ascii")
        return self._request(url, data=data, max_bytes=MAX_HTML_BYTES)

    def _request(self, url: str, *, data: bytes | None, max_bytes: int) -> _Response:
        for attempt in range(2):
            self._wait_for_request_slot()
            headers = {
                "Accept": "text/html,application/xhtml+xml,image/avif,image/webp,image/*,*/*;q=0.8",
                "User-Agent": USER_AGENT,
            }
            if data is not None:
                headers["Content-Type"] = "application/x-www-form-urlencoded"
            request = Request(url, data=data, headers=headers)
            try:
                with self.opener.open(  # noqa: S310 - fixed public HTTPS endpoints.
                    request,
                    timeout=REQUEST_TIMEOUT_SECONDS,
                ) as response:
                    body = response.read(max_bytes + 1)
                    if len(body) > max_bytes:
                        raise _FetchError(f"response exceeded {max_bytes // (1024 * 1024)} MiB")
                    if not body:
                        raise _FetchError("server returned an empty response")
                    return _Response(
                        body=body,
                        content_type=response.headers.get_content_type().casefold(),
                        final_url=response.geturl(),
                    )
            except HTTPError as error:
                transient = error.code in TRANSIENT_HTTP_STATUSES
                reason = f"HTTP {error.code}"
            except (HTTPException, TimeoutError) as error:
                transient = True
                reason = str(error)
            except URLError as error:
                transient = True
                reason = str(error.reason)
            except OSError as error:
                transient = True
                reason = str(error)
            except ValueError as error:
                transient = False
                reason = str(error)

            if attempt == 0 and transient:
                continue
            raise _FetchError(_one_line(reason)) from None

        raise _FetchError("request failed")

    def _wait_for_request_slot(self) -> None:
        now = time.monotonic()
        if self._last_request_started is not None:
            remaining = self.delay - (now - self._last_request_started)
            if remaining > 0:
                time.sleep(remaining)
        self._last_request_started = time.monotonic()


class _SearchFormParser(HTMLParser):
    """Inspect the real basic-search form instead of guessing its field names."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.method = ""
        self.action = ""
        self.controls: list[_FormControl] = []
        self._in_target_form = False
        self._select: dict[str, object] | None = None
        self._textarea: dict[str, object] | None = None

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        attributes = {name.casefold(): value for name, value in attrs}
        if tag == "form":
            name = attributes.get("name") or ""
            action = attributes.get("action") or ""
            self._in_target_form = name == "searchCriteriaForm" or (
                "publicSearchColasBasicProcess.do" in action
            )
            if self._in_target_form:
                self.method = (attributes.get("method") or "get").casefold()
                self.action = action
            return
        if not self._in_target_form:
            return

        if tag == "input":
            self._add_input(attributes)
        elif tag == "select":
            name = attributes.get("name") or ""
            if name and "disabled" not in attributes:
                self._select = {"name": name, "options": [], "multiple": "multiple" in attributes}
        elif tag == "option" and self._select is not None:
            options = self._select["options"]
            assert isinstance(options, list)
            options.append(
                {
                    "value": attributes.get("value"),
                    "selected": "selected" in attributes,
                    "text": [],
                }
            )
        elif tag == "textarea":
            name = attributes.get("name") or ""
            if name and "disabled" not in attributes:
                self._textarea = {"name": name, "text": []}

    def handle_endtag(self, tag: str) -> None:
        if tag == "form" and self._in_target_form:
            self._in_target_form = False
        elif tag == "select" and self._select is not None:
            self._finish_select()
        elif tag == "textarea" and self._textarea is not None:
            text = self._textarea["text"]
            assert isinstance(text, list)
            self.controls.append(
                _FormControl(
                    name=str(self._textarea["name"]),
                    value="".join(text),
                    kind="textarea",
                )
            )
            self._textarea = None

    def handle_data(self, data: str) -> None:
        if self._textarea is not None:
            text = self._textarea["text"]
            assert isinstance(text, list)
            text.append(data)
        if self._select is not None:
            options = self._select["options"]
            assert isinstance(options, list)
            if options:
                option_text = options[-1]["text"]
                assert isinstance(option_text, list)
                option_text.append(data)

    def form(self) -> _SearchForm:
        if not self.method:
            raise _SearchError("basic-search page did not contain searchCriteriaForm")
        return _SearchForm(self.method, self.action, tuple(self.controls))

    def _add_input(self, attributes: dict[str, str | None]) -> None:
        name = attributes.get("name") or ""
        kind = (attributes.get("type") or "text").casefold()
        if not name or "disabled" in attributes or kind in {"button", "file", "reset", "submit"}:
            return
        if kind in {"checkbox", "radio"} and "checked" not in attributes:
            return
        self.controls.append(
            _FormControl(
                name=name,
                value=attributes.get("value") or ("on" if kind in {"checkbox", "radio"} else ""),
                kind=kind,
            )
        )

    def _finish_select(self) -> None:
        assert self._select is not None
        options = self._select["options"]
        assert isinstance(options, list)
        selected = [option for option in options if option["selected"]]
        if not selected and options:
            selected = options[:1]
        if not self._select["multiple"] and selected:
            selected = selected[:1]
        for option in selected:
            option_text = option["text"]
            assert isinstance(option_text, list)
            value = option["value"]
            self.controls.append(
                _FormControl(
                    name=str(self._select["name"]),
                    value=str(value) if value is not None else "".join(option_text).strip(),
                    kind="select",
                )
            )
        self._select = None


class _RegistryHTMLParser(HTMLParser):
    """Collect rendered text and relevant registry links without a DOM dependency."""

    _BREAK_TAGS = frozenset(
        {
            "br",
            "dd",
            "div",
            "dl",
            "dt",
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
            "li",
            "p",
            "section",
            "table",
            "td",
            "th",
            "tr",
        }
    )

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hrefs: list[str] = []
        self.image_sources: list[str] = []
        self._ignored_tag: str | None = None

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        if tag in {"script", "style"}:
            self._ignored_tag = tag
            return
        if self._ignored_tag is not None:
            return
        if tag in self._BREAK_TAGS:
            self.parts.append("\n")
        attributes = {name.casefold(): value for name, value in attrs}
        if tag == "a" and attributes.get("href"):
            self.hrefs.append(str(attributes["href"]))
        elif tag == "img" and attributes.get("src"):
            self.image_sources.append(str(attributes["src"]))

    def handle_endtag(self, tag: str) -> None:
        if tag == self._ignored_tag:
            self._ignored_tag = None
            return
        if self._ignored_tag is None and tag in self._BREAK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._ignored_tag is None:
            self.parts.append(data)

    def lines(self) -> list[str]:
        return [
            line for raw_line in "".join(self.parts).splitlines() if (line := _one_line(raw_line))
        ]


def _one_line(value: object) -> str:
    return " ".join(str(value).replace("\xa0", " ").split()) or "unknown error"


def _positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return number


def _nonnegative_float(value: str) -> float:
    number = float(value)
    if number < 0:
        raise argparse.ArgumentTypeError("must be zero or greater")
    return number


def _product_pattern(value: str) -> str:
    if not value.strip():
        raise argparse.ArgumentTypeError("must not be blank")
    return value.strip()


def _ttbid(value: str) -> str:
    if re.fullmatch(r"\d{14}", value) is None:
        raise argparse.ArgumentTypeError("must be a 14-digit TTB ID")
    return value


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch real approved alcohol labels from the TTB Public COLA Registry."
    )
    parser.add_argument("--limit", type=_positive_int, default=20, help="maximum images to keep")
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(".real_labels"),
        help="corpus directory (default: .real_labels)",
    )
    parser.add_argument(
        "--delay",
        type=_nonnegative_float,
        default=DEFAULT_DELAY_SECONDS,
        help="minimum delay between requests in seconds (default: 1.0)",
    )
    parser.add_argument(
        "--product",
        type=_product_pattern,
        default=DEFAULT_PRODUCT,
        help="TTB product-name pattern (default: %%WHISKEY%%)",
    )
    parser.add_argument(
        "--ttbid",
        type=_ttbid,
        action="append",
        default=[],
        help="fetch one TTB ID directly; repeat to bypass search with multiple IDs",
    )
    return parser.parse_args(argv)


def _decode_html(response: _Response) -> str:
    return response.body.decode("utf-8", errors="replace")


def _normalized_control_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.casefold())


def _find_search_field(
    form: _SearchForm,
    suffix: str,
    *,
    accepted_kinds: frozenset[str] | None = None,
) -> str:
    candidates = [
        control
        for control in form.controls
        if _normalized_control_name(control.name).endswith(suffix)
        and (accepted_kinds is None or control.kind in accepted_kinds)
    ]
    names = list(dict.fromkeys(control.name for control in candidates))
    if len(names) != 1:
        available = ", ".join(dict.fromkeys(control.name for control in form.controls))
        raise _SearchError(
            f"could not identify one {suffix} field in searchCriteriaForm; controls: {available}"
        )
    return names[0]


def _search_fields(search_page_html: str, product: str) -> list[tuple[str, str]]:
    parser = _SearchFormParser()
    parser.feed(search_page_html)
    form = parser.form()
    if form.method != "post":
        raise _SearchError(f"searchCriteriaForm uses unexpected {form.method.upper()} method")

    date_from_name = _find_search_field(form, "datecompletedfrom")
    date_to_name = _find_search_field(form, "datecompletedto")
    product_name = _find_search_field(
        form,
        "productname",
        accepted_kinds=frozenset({"search", "text", "textarea"}),
    )
    replaced_names = {date_from_name, date_to_name, product_name}
    fields = [
        (control.name, control.value)
        for control in form.controls
        if control.name not in replaced_names
    ]
    today = date.today()
    fields.extend(
        (
            (date_from_name, (today - timedelta(days=365)).strftime("%m/%d/%Y")),
            (date_to_name, today.strftime("%m/%d/%Y")),
            (product_name, product),
        )
    )
    return fields


def _ttbids_from_results(html_text: str) -> list[str]:
    parser = _RegistryHTMLParser()
    parser.feed(html_text)
    ttbids: list[str] = []
    for href in parser.hrefs:
        if "viewcoladetails" not in href.casefold():
            continue
        values = parse_qs(urlparse(urljoin(BASE_URL, href)).query).get("ttbid", [])
        ttbids.extend(value for value in values if re.fullmatch(r"\d{14}", value))
        match = re.search(r"viewColaDetails\(['\"]?(\d{14})", href, flags=re.IGNORECASE)
        if match is not None:
            ttbids.append(match.group(1))

    for match in re.finditer(
        r"viewColaDetails.{0,300}?ttbid(?:=|%3D)(\d{14})",
        html_text,
        flags=re.IGNORECASE | re.DOTALL,
    ):
        ttbids.append(match.group(1))
    return list(dict.fromkeys(ttbids))


def _search_ttbids(client: _PoliteClient, search_page_html: str, product: str) -> list[str]:
    fields = _search_fields(search_page_html, product)
    response = client.post(SEARCH_RESULTS_URL, fields)
    results_html = _decode_html(response)
    ttbids = _ttbids_from_results(results_html)
    if not ttbids:
        raise _SearchError(
            "search response contained no viewColaDetails links; retry with explicit --ttbid values"
        )
    return ttbids


def _detail_url(ttbid: str, action: str) -> str:
    return f"{DETAIL_URL}?{urlencode({'action': action, 'ttbid': ttbid})}"


def _strip_help_text(value: str) -> str:
    return re.sub(
        r"^Open help for .*? in a new window\s*",
        "",
        value,
        flags=re.IGNORECASE,
    ).strip()


def _line_starts_with_label(line: str) -> bool:
    folded = line.casefold()
    return any(folded.startswith(label.casefold()) for label in DETAIL_LABELS)


def _field_value(lines: Sequence[str], label: str) -> str:
    folded_label = label.casefold()
    for index, line in enumerate(lines):
        position = line.casefold().find(folded_label)
        if position < 0:
            continue
        remainder = _strip_help_text(line[position + len(label) :])
        if remainder:
            return remainder
        for candidate in lines[index + 1 :]:
            if _line_starts_with_label(candidate):
                break
            cleaned = _strip_help_text(candidate)
            if cleaned:
                return cleaned
    return ""


def _looks_like_permit_number(value: str) -> bool:
    compact = value.strip().upper()
    if " " in compact or "-" not in compact:
        return False
    return re.fullmatch(r"[A-Z0-9]{1,8}(?:-[A-Z0-9]{1,10}){1,5}", compact) is not None


def _plant_address(lines: Sequence[str]) -> str:
    collected: list[str] = []
    for index, line in enumerate(lines):
        position = line.casefold().find(PLANT_LABEL.casefold())
        if position < 0:
            continue
        remainder = _strip_help_text(line[position + len(PLANT_LABEL) :])
        if remainder:
            collected.append(remainder)
        for candidate in lines[index + 1 : index + 16]:
            if any(candidate.casefold().startswith(stop.casefold()) for stop in PLANT_STOP_LABELS):
                break
            if _line_starts_with_label(candidate):
                break
            cleaned = _strip_help_text(candidate)
            if cleaned:
                collected.append(cleaned)
        break

    address_parts = [
        part
        for part in dict.fromkeys(collected)
        if part.casefold() not in {"none", "n/a"} and not _looks_like_permit_number(part)
    ]
    return " / ".join(address_parts)


def _origin_country(origin_code: str) -> str:
    normalized = _one_line(origin_code).upper()
    return "" if not origin_code or normalized in DOMESTIC_ORIGINS else origin_code


def _parse_record(ttbid: str, detail_html: str, source_url: str) -> _RegistryRecord:
    parser = _RegistryHTMLParser()
    parser.feed(detail_html)
    lines = parser.lines()
    brand_name = _field_value(lines, "Brand Name:")
    class_type = _field_value(lines, "Class/Type Code:")
    if not brand_name or not class_type:
        raise ValueError("detail page did not contain both Brand Name and Class/Type Code")
    origin_code = _field_value(lines, "Origin Code:")
    return _RegistryRecord(
        ttbid=ttbid,
        brand_name=brand_name,
        fanciful_name=_field_value(lines, "Fanciful Name:"),
        class_type=class_type,
        origin_code=origin_code,
        origin_country=_origin_country(origin_code),
        bottler=_plant_address(lines),
        source_url=source_url,
    )


def _attachment_urls(printable_html: str) -> list[str]:
    parser = _RegistryHTMLParser()
    parser.feed(printable_html)
    urls: list[str] = []
    for source in parser.image_sources:
        absolute = urljoin(BASE_URL, source)
        parsed = urlparse(absolute)
        if not parsed.path.endswith("/publicViewAttachment.do"):
            continue
        query = parse_qs(parsed.query)
        if query.get("filetype") == ["l"] and query.get("filename"):
            urls.append(absolute)
    return list(dict.fromkeys(urls))


def _jpeg_bytes(data: bytes) -> tuple[bytes, int, int]:
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(BytesIO(data)) as probe:
            width, height = probe.size
            image_format = probe.format
            if width < 1 or height < 1:
                raise ValueError("image has invalid dimensions")
            if width * height > MAX_IMAGE_PIXELS:
                raise ValueError(f"image exceeds {MAX_IMAGE_PIXELS:,} pixels")
            probe.verify()

        with Image.open(BytesIO(data)) as image:
            image.load()
            if image_format == "JPEG":
                return data, width, height
            converted = image.convert("RGB")
            output = BytesIO()
            converted.save(output, format="JPEG", quality=95)
            return output.getvalue(), width, height


def _ground_truth(record: _RegistryRecord) -> dict[str, str]:
    return {
        "ttbid": record.ttbid,
        "brand_name": record.brand_name,
        "fanciful_name": record.fanciful_name,
        "class_type": record.class_type,
        "origin_code": record.origin_code,
        "origin_country": record.origin_country,
        "bottler": record.bottler,
        "source_url": record.source_url,
    }


def _manifest_row(filename: str, record: _RegistryRecord) -> dict[str, str]:
    return {
        "filename": filename,
        "brand_name": record.brand_name,
        "class_type": record.class_type,
        "alcohol_content": "",
        "net_contents": "",
        "bottler": record.bottler,
        "origin_country": record.origin_country,
    }


def _write_image(path: Path, data: bytes) -> None:
    temporary_path = path.with_name(f".{path.name}.tmp")
    try:
        temporary_path.write_bytes(data)
        temporary_path.replace(path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _fetch_record(
    client: _PoliteClient,
    ttbid: str,
    images_directory: Path,
    stats: _RunStats,
    remaining: int,
) -> list[_KeptImage]:
    detail_source_url = _detail_url(ttbid, "publicDisplaySearchBasic")
    detail_response = client.get(detail_source_url, max_bytes=MAX_HTML_BYTES)
    record = _parse_record(ttbid, _decode_html(detail_response), detail_source_url)

    printable_url = _detail_url(ttbid, "publicFormDisplay")
    printable_response = client.get(printable_url, max_bytes=MAX_HTML_BYTES)
    attachments = _attachment_urls(_decode_html(printable_response))
    if not attachments:
        stats.skip(ttbid, "printable form contained no label-image attachments")
        return []

    kept: list[_KeptImage] = []
    for attachment_number, attachment_url in enumerate(attachments, start=1):
        if len(kept) >= remaining:
            break
        try:
            response = client.get(attachment_url, max_bytes=MAX_IMAGE_BYTES)
            if response.content_type == "text/html" or response.body.lstrip()[
                :20
            ].lower().startswith((b"<!doctype html", b"<html")):
                raise _FetchError("attachment returned HTML; the COLAs Online session is invalid")
            jpeg_data, width, height = _jpeg_bytes(response.body)
            filename = f"{ttbid}-{attachment_number}.jpg"
            _write_image(images_directory / filename, jpeg_data)
        except (
            _FetchError,
            Image.DecompressionBombError,
            Image.DecompressionBombWarning,
            UnidentifiedImageError,
            OSError,
            SyntaxError,
            ValueError,
        ) as error:
            stats.skip(f"{ttbid} attachment {attachment_number}", error)
            continue

        kept_image = _KeptImage(
            filename=filename,
            width=width,
            height=height,
            ground_truth=_ground_truth(record),
            manifest_row=_manifest_row(filename, record),
        )
        kept.append(kept_image)
        print(f"kept {filename}: {width}x{height}")
    return kept


def _write_metadata(out_directory: Path, images: Sequence[_KeptImage]) -> None:
    ground_truth_path = out_directory / "ground_truth.json"
    manifest_path = out_directory / "manifest.csv"
    temporary_ground_truth = out_directory / ".ground_truth.json.tmp"
    temporary_manifest = out_directory / ".manifest.csv.tmp"
    try:
        temporary_ground_truth.write_text(
            json.dumps(
                {image.filename: image.ground_truth for image in images},
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        with temporary_manifest.open("w", encoding="utf-8", newline="") as manifest_file:
            writer = csv.DictWriter(
                manifest_file,
                fieldnames=MANIFEST_COLUMNS,
                lineterminator="\n",
            )
            writer.writeheader()
            writer.writerows(image.manifest_row for image in images)
        temporary_ground_truth.replace(ground_truth_path)
        temporary_manifest.replace(manifest_path)
    finally:
        temporary_ground_truth.unlink(missing_ok=True)
        temporary_manifest.unlink(missing_ok=True)


def _remove_stale_images(images_directory: Path, images: Sequence[_KeptImage]) -> None:
    kept_filenames = {image.filename for image in images}
    for image_path in images_directory.glob("*.jpg"):
        if image_path.name not in kept_filenames:
            image_path.unlink()


def _fetch_corpus(
    *,
    limit: int,
    out_directory: Path,
    delay: float,
    product: str,
    explicit_ttbids: Sequence[str],
) -> tuple[list[_KeptImage], _RunStats, str | None]:
    images_directory = out_directory / "images"
    images_directory.mkdir(parents=True, exist_ok=True)
    client = _PoliteClient(delay)
    stats = _RunStats()

    try:
        search_page_response = client.get(SEARCH_PAGE_URL, max_bytes=MAX_HTML_BYTES)
        search_page_html = _decode_html(search_page_response)
    except _FetchError as error:
        stats.skip("session", error)
        return [], stats, "could not establish the COLAs Online session"

    if explicit_ttbids:
        ttbids = list(dict.fromkeys(explicit_ttbids))
    else:
        try:
            ttbids = _search_ttbids(client, search_page_html, product)
        except (_FetchError, _SearchError) as error:
            stats.skip("search", error)
            return [], stats, "registry search failed; retry with one or more --ttbid values"

    kept: list[_KeptImage] = []
    for ttbid in ttbids:
        if len(kept) >= limit:
            break
        try:
            kept.extend(
                _fetch_record(
                    client,
                    ttbid,
                    images_directory,
                    stats,
                    limit - len(kept),
                )
            )
        except (
            _FetchError,
            UnidentifiedImageError,
            OSError,
            SyntaxError,
            ValueError,
        ) as error:
            stats.skip(ttbid, error)

    if kept:
        try:
            _write_metadata(out_directory, kept)
            _remove_stale_images(images_directory, kept)
        except OSError as error:
            return kept, stats, f"could not finalize corpus metadata: {_one_line(error)}"
    return kept, stats, None


def main(argv: Sequence[str] | None = None) -> int:
    """Build a local, gitignored corpus while isolating bad registry records."""

    args = _parse_args(argv)
    images, stats, run_error = _fetch_corpus(
        limit=args.limit,
        out_directory=args.out,
        delay=args.delay,
        product=args.product,
        explicit_ttbids=args.ttbid,
    )
    origins = sum(bool(image.ground_truth["origin_country"]) for image in images)
    print(f"Summary: kept={len(images)} skipped={stats.skipped} with_origin_country={origins}")
    if run_error is not None:
        print(f"error: {run_error}", file=sys.stderr)
        return 1
    if not images:
        print("error: no label images were kept", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
