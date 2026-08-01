import re
import unicodedata
from decimal import Decimal
from difflib import SequenceMatcher

from labelcheck.config import (
    ABV_MARKER_SIGNAL_PATTERN,
    ABV_PATTERN,
    APOSTROPHE_CHARACTERS,
    BEVERAGE_CLASS_KEYWORDS,
    BOTTLER_PREFIX_TOKEN_SEQUENCES,
    FUZZY_UNICODE_NORMALIZATION_FORM,
    GOVERNMENT_WARNING_PREFIX,
    LEGAL_SUFFIX_TOKEN_SEQUENCES,
    MAX_ABV_PERCENT,
    MAX_PROOF,
    MIN_ABV_PERCENT,
    MIN_PROOF,
    NET_CONTENT_UNIT_TO_ML,
    NET_CONTENTS_PATTERN,
    NUMBER_PATTERN,
    ORIGIN_PREFIX_TOKEN_SEQUENCES,
    PROOF_MARKER_PATTERN,
    PROOF_PATTERN,
    WARNING_ENUMERATOR_ONE_PATTERN,
    WARNING_HYPHENATION_PATTERN,
    WARNING_LIGATURE_REPLACEMENTS,
    WARNING_LOWERCASE_L_PATTERN,
    WARNING_TOKEN_PATTERN,
    WARNING_UPPERCASE_I_PATTERN,
)


def _require_text(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("normalization requires a string")
    return value


def collapse_whitespace(value: str) -> str:
    """Treat line wrapping and Unicode spacing as layout rather than label content."""

    return " ".join(_require_text(value).split())


def _normalize_identity_characters(value: str) -> str:
    normalized = unicodedata.normalize(FUZZY_UNICODE_NORMALIZATION_FORM, value).casefold()
    characters: list[str] = []
    for character in normalized:
        if character in APOSTROPHE_CHARACTERS:
            continue
        if character.isalnum() or character.isspace():
            characters.append(character)
        else:
            characters.append(" ")
    return collapse_whitespace("".join(characters))


def normalize_identity_text(value: str) -> str:
    """Remove cosmetic text variation while retaining every substantive word."""

    return _normalize_identity_characters(_require_text(value))


def normalize_fuzzy_text(value: str) -> str:
    """Remove legal-entity noise before human-tolerant fuzzy comparisons."""

    tokens = _normalize_identity_characters(_require_text(value)).split()
    suffix_removed = True
    while tokens and suffix_removed:
        suffix_removed = False
        for suffix in LEGAL_SUFFIX_TOKEN_SEQUENCES:
            if len(tokens) > len(suffix) and tuple(tokens[-len(suffix) :]) == suffix:
                del tokens[-len(suffix) :]
                suffix_removed = True
                break
    return " ".join(tokens)


def normalize_compact_fuzzy_text(value: str) -> str:
    """Treat lost OCR word boundaries as layout while preserving character order."""

    return normalize_fuzzy_text(value).replace(" ", "")


def normalize_bottler_text(value: str) -> str:
    """Remove bottling boilerplate before comparing a producer identity and address."""

    tokens = normalize_identity_text(value).split()
    for prefix in BOTTLER_PREFIX_TOKEN_SEQUENCES:
        if tuple(tokens[: len(prefix)]) == prefix:
            return " ".join(tokens[len(prefix) :])
    return " ".join(tokens)


def normalize_compact_bottler_text(value: str) -> str:
    """Keep lost OCR word boundaries from turning an exact bottler into a mismatch."""

    return normalize_bottler_text(value).replace(" ", "")


def normalize_origin_text(value: str) -> str:
    """Remove standard label boilerplate before comparing a manifest country value."""

    tokens = normalize_identity_text(value).split()
    for prefix in ORIGIN_PREFIX_TOKEN_SEQUENCES:
        if tuple(tokens[: len(prefix)]) == prefix:
            return " ".join(tokens[len(prefix) :])
    return " ".join(tokens)


def normalize_warning_text(value: str) -> str:
    """Repair only documented OCR/layout artifacts without erasing statutory case."""

    normalized = _require_text(value)
    for ligature, expansion in WARNING_LIGATURE_REPLACEMENTS.items():
        normalized = normalized.replace(ligature, expansion)
    normalized = re.sub(WARNING_HYPHENATION_PATTERN, "", normalized)
    normalized = re.sub(WARNING_LOWERCASE_L_PATTERN, "l", normalized)
    normalized = re.sub(WARNING_UPPERCASE_I_PATTERN, "I", normalized)
    normalized = re.sub(WARNING_ENUMERATOR_ONE_PATTERN, "(1)", normalized)
    return collapse_whitespace(normalized)


def extract_warning_prefix(value: str) -> str:
    """Isolate the independently regulated prefix after warning-safe OCR repairs."""

    normalized = normalize_warning_text(value)
    return normalized[: len(GOVERNMENT_WARNING_PREFIX)]


def normalize_number(value: str) -> Decimal:
    """Use Decimal so unit and alcohol comparisons never inherit binary-float error."""

    stripped = _require_text(value).strip()
    if re.fullmatch(NUMBER_PATTERN, stripped) is None:
        raise ValueError(f"invalid numeric value: {value!r}")
    return Decimal(stripped.replace(",", ""))


def parse_abv(value: str) -> Decimal | None:
    """Anchor an ABV number to a percent marker so unrelated label numbers are ignored."""

    text = _require_text(value)
    matches = list(re.finditer(ABV_PATTERN, text, flags=re.IGNORECASE))
    if not matches:
        if re.search(ABV_MARKER_SIGNAL_PATTERN, text, flags=re.IGNORECASE):
            raise ValueError("ABV marker is present without a valid numeric declaration")
        return None
    if len(matches) > 1:
        raise ValueError("multiple ABV values are ambiguous")
    numeric_text = matches[0].group("before") or matches[0].group("after")
    abv = normalize_number(numeric_text)
    if not MIN_ABV_PERCENT <= abv <= MAX_ABV_PERCENT:
        raise ValueError("ABV must be between 0 and 100 percent")
    return abv


def parse_proof(value: str) -> Decimal | None:
    """Anchor proof to its marker so ABV and container-size numbers cannot be confused."""

    text = _require_text(value)
    matches = list(re.finditer(PROOF_PATTERN, text, flags=re.IGNORECASE))
    if not matches:
        if re.search(PROOF_MARKER_PATTERN, text, flags=re.IGNORECASE):
            raise ValueError("proof marker is present without a valid numeric declaration")
        return None
    if len(matches) > 1:
        raise ValueError("multiple proof values are ambiguous")
    numeric_text = matches[0].group("before") or matches[0].group("after")
    proof = normalize_number(numeric_text)
    if not MIN_PROOF <= proof <= MAX_PROOF:
        raise ValueError("proof must be between 0 and 200")
    return proof


def parse_net_contents_ml(value: str) -> Decimal:
    """Convert supported volume declarations to one exact milliliter representation."""

    amount_ml, _unit = parse_net_contents(value)
    return amount_ml


def parse_net_contents(value: str) -> tuple[Decimal, str]:
    """Retain the source unit so comparison can scope display-rounding tolerance safely."""

    match = re.fullmatch(NET_CONTENTS_PATTERN, _require_text(value), flags=re.IGNORECASE)
    if match is None:
        raise ValueError(f"unsupported net-contents value: {value!r}")
    amount = normalize_number(match.group("value"))
    unit = collapse_whitespace(match.group("unit").casefold().replace(".", ""))
    try:
        multiplier = NET_CONTENT_UNIT_TO_ML[unit]
    except KeyError as error:
        raise ValueError(f"unsupported net-contents unit: {unit!r}") from error
    return amount * multiplier, unit


def canonical_beverage_class(value: str) -> str | None:
    """Map label class wording to the key used by the class-specific tolerance table."""

    normalized = normalize_identity_text(value)
    padded = f" {normalized} "
    best_match: str | None = None
    best_length = 0
    for canonical, keywords in BEVERAGE_CLASS_KEYWORDS:
        for keyword in keywords:
            keyword_length = len(keyword.split())
            if f" {keyword} " in padded and keyword_length > best_length:
                best_match = canonical
                best_length = keyword_length
    return best_match


def word_level_diff(expected: str, extracted: str) -> str:
    """Describe deviations directionally so an agent can act without comparing paragraphs."""

    expected_tokens = re.findall(WARNING_TOKEN_PATTERN, _require_text(expected))
    extracted_tokens = re.findall(WARNING_TOKEN_PATTERN, _require_text(extracted))
    differences: list[str] = []
    matcher = SequenceMatcher(a=expected_tokens, b=extracted_tokens, autojunk=False)

    for (
        operation,
        expected_start,
        expected_end,
        extracted_start,
        extracted_end,
    ) in matcher.get_opcodes():
        if operation == "equal":
            continue
        expected_segment = " ".join(expected_tokens[expected_start:expected_end])
        extracted_segment = " ".join(extracted_tokens[extracted_start:extracted_end])
        if operation == "delete":
            differences.append(f"missing expected [{expected_segment}]")
        elif operation == "insert":
            differences.append(f"unexpected extracted [{extracted_segment}]")
        else:
            differences.append(
                f"replace expected [{expected_segment}] with extracted [{extracted_segment}]"
            )

    return "; ".join(differences)
