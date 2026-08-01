from decimal import Decimal

# Derived from the stakeholder acceptance cases and backed by explicit REVIEW-band tests.
FUZZY_PASS_THRESHOLD = 90.0
FUZZY_REVIEW_THRESHOLD = 70.0

EXACT_MATCH_CONFIDENCE = 100.0
MISMATCH_CONFIDENCE = 0.0

LEGAL_SUFFIX_TOKEN_SEQUENCES = (
    ("limited", "liability", "company"),
    ("incorporated",),
    ("corporation",),
    ("company",),
    ("limited",),
    ("llc",),
    ("l", "l", "c"),
    ("inc",),
    ("ltd",),
    ("corp",),
    ("co",),
    ("plc",),
    ("llp",),
    ("lp",),
)
ORIGIN_PREFIX_TOKEN_SEQUENCES = (
    ("product", "of"),
    ("made", "in"),
    ("produced", "in"),
    ("imported", "from"),
)
FUZZY_UNICODE_NORMALIZATION_FORM = "NFKC"
APOSTROPHE_CHARACTERS = frozenset(("'", "’", "ʼ"))

NUMBER_PATTERN = r"(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.[0-9]+)?|\.[0-9]+"
NUMBER_CANDIDATE_PATTERN = r"[+-]?(?:[0-9][0-9.,]*|\.[0-9][0-9.,]*)"
ABV_MARKER_PATTERN = (
    r"(?:\balc(?:ohol)?\.?\s*/\s*vol(?:ume)?\b\.?|\babv\b|\balcohol\s+by\s+volume\b)"
)
ABV_MARKER_SIGNAL_PATTERN = r"\b(?:alc|alcohol|abv)\b"
ABV_PATTERN = (
    rf"(?:(?<![0-9A-Za-z.,+\-])(?P<before>{NUMBER_CANDIDATE_PATTERN})\s*%\s*"
    rf"{ABV_MARKER_PATTERN}|{ABV_MARKER_PATTERN}\s*"
    rf"(?P<after>{NUMBER_CANDIDATE_PATTERN})\s*%(?![0-9A-Za-z.,+\-]))"
)
PROOF_MARKER_PATTERN = r"\bproof\b"
PROOF_PATTERN = (
    rf"(?:(?<![0-9A-Za-z.,+\-])(?P<before>{NUMBER_CANDIDATE_PATTERN})\s*"
    rf"{PROOF_MARKER_PATTERN}|{PROOF_MARKER_PATTERN}\s*"
    rf"(?P<after>{NUMBER_CANDIDATE_PATTERN})(?![0-9A-Za-z.,+\-]))"
)
NET_CONTENTS_PATTERN = (
    rf"^\s*(?P<value>{NUMBER_PATTERN})\s*"
    r"(?P<unit>fl\.?\s*oz\.?|ml|millilit(?:er|re)s?|l|lit(?:er|re)s?)\s*$"
)

MIN_ABV_PERCENT = Decimal("0")
MAX_ABV_PERCENT = Decimal("100")
MIN_PROOF = Decimal("0")
MAX_PROOF = Decimal("200")
PROOF_MULTIPLIER = Decimal("2")
PROOF_ABV_TOLERANCE = Decimal("0")

# TTB tolerances for labeled alcohol content, in PERCENTAGE POINTS of ABV. Retrieved
# 2026-07-31 from the eCFR versioner API (the same publisher and endpoint used for the
# statutory warning in docs/cfr/27-cfr-16-21.txt).
#
# Distilled spirits — 27 CFR 5.65 "Alcohol content.":
#   "A tolerance of plus or minus 0.3 percentage points is allowed for actual alcohol
#    content that is above or below the labeled alcohol content."
#
# Malt beverages — 27 CFR 7.65:
#   "a tolerance of 0.3 percentage points will be permitted, either above or below the
#    stated alcohol content, for malt beverages containing 0.5 percent or more alcohol
#    by volume."
#   The tolerance is therefore conditional: it does not extend to products at or below
#   0.5% ABV, which is where "non-alcoholic" and "alcohol free" claims live.
#
# Wine — 27 CFR 4.36(b): the tolerance is BANDED by strength, not flat:
#   "a tolerance of 1 percent, in the case of wines containing more than 14 percent of
#    alcohol by volume ... of 1.5 percent, in the case of wines containing 14 percent or
#    less of alcohol by volume, will be permitted either above or below the stated
#    percentage"
#
# Because two of the three classes are conditional, the tolerance cannot be a flat
# per-class scalar. Resolve it through abv_tolerance_for() below.
DISTILLED_SPIRITS_ABV_TOLERANCE = Decimal("0.3")  # 27 CFR 5.65
MALT_BEVERAGE_ABV_TOLERANCE = Decimal("0.3")  # 27 CFR 7.65
MALT_BEVERAGE_TOLERANCE_MIN_ABV = Decimal("0.5")  # 27 CFR 7.65
WINE_ABV_BAND_THRESHOLD = Decimal("14")  # 27 CFR 4.36(b)
WINE_ABV_TOLERANCE_AT_OR_BELOW_BAND = Decimal("1.5")  # 27 CFR 4.36(b)
WINE_ABV_TOLERANCE_ABOVE_BAND = Decimal("1.0")  # 27 CFR 4.36(b)
NO_ABV_TOLERANCE = Decimal("0")


def abv_tolerance_for(canonical_class: str, labeled_abv: Decimal) -> Decimal:
    """Permitted ABV deviation in percentage points, per the CFR citations above.

    Takes the labeled ABV because two of the three classes gate their tolerance on it:
    wine's steps down above 14%, and a malt beverage at or below 0.5% gets none at all.
    """
    if canonical_class == "distilled_spirits":
        return DISTILLED_SPIRITS_ABV_TOLERANCE
    if canonical_class == "wine":
        if labeled_abv > WINE_ABV_BAND_THRESHOLD:
            return WINE_ABV_TOLERANCE_ABOVE_BAND
        return WINE_ABV_TOLERANCE_AT_OR_BELOW_BAND
    if canonical_class == "beer":
        if labeled_abv < MALT_BEVERAGE_TOLERANCE_MIN_ABV:
            return NO_ABV_TOLERANCE
        return MALT_BEVERAGE_ABV_TOLERANCE
    raise KeyError(f"No CFR-sourced ABV tolerance for beverage class {canonical_class!r}")


BEVERAGE_CLASS_KEYWORDS = (
    (
        "beer",
        ("beer", "ale", "lager", "malt beverage", "barley wine", "porter", "stout"),
    ),
    ("wine", ("wine", "cabernet", "merlot", "chardonnay", "pinot", "riesling")),
    (
        "distilled_spirits",
        (
            "distilled spirits",
            "distilled spirit",
            "spirits",
            "spirit",
            "whiskey",
            "whisky",
            "bourbon",
            "vodka",
            "gin",
            "rum",
            "brandy",
            "tequila",
        ),
    ),
)

MILLILITERS_PER_LITER = Decimal("1000")
FLUID_OUNCE_TO_ML = Decimal("29.5735295625")
# Formatting tolerance only: it permits a two-decimal fl-oz rendering such as 25.36 fl oz.
FLUID_OUNCE_ROUNDING_TOLERANCE_ML = Decimal("0.05")
NET_CONTENTS_EXACT_TOLERANCE_ML = Decimal("0")
NET_CONTENT_UNIT_TO_ML = {
    "ml": Decimal("1"),
    "milliliter": Decimal("1"),
    "milliliters": Decimal("1"),
    "millilitre": Decimal("1"),
    "millilitres": Decimal("1"),
    "l": MILLILITERS_PER_LITER,
    "liter": MILLILITERS_PER_LITER,
    "liters": MILLILITERS_PER_LITER,
    "litre": MILLILITERS_PER_LITER,
    "litres": MILLILITERS_PER_LITER,
    "fl oz": FLUID_OUNCE_TO_ML,
}

WARNING_HYPHENATION_PATTERN = r"(?<=[A-Za-z])-[ \t]*\r?\n[ \t]*(?=[A-Za-z])"
WARNING_LOWERCASE_L_PATTERN = r"(?<=[a-z])(?:1|I)(?=[a-z])"
WARNING_UPPERCASE_I_PATTERN = r"(?<=[A-Z])(?:1|l)(?=[A-Z])"
WARNING_ENUMERATOR_ONE_PATTERN = r"\((?:I|l)\)"
WARNING_TOKEN_PATTERN = r"[A-Za-z0-9]+|[^\w\s]"
WARNING_LIGATURE_REPLACEMENTS = {
    "ﬀ": "ff",
    "ﬁ": "fi",
    "ﬂ": "fl",
    "ﬃ": "ffi",
    "ﬄ": "ffl",
}

GOVERNMENT_WARNING_PREFIX = "GOVERNMENT WARNING:"
GOVERNMENT_WARNING = (
    "GOVERNMENT WARNING: (1) According to the Surgeon General, women should not drink "
    "alcoholic beverages during pregnancy because of the risk of birth defects. (2) "
    "Consumption of alcoholic beverages impairs your ability to drive a car or operate "
    "machinery, and may cause health problems."
)
WARNING_BOLD_EXPECTATION = "Bold GOVERNMENT WARNING: prefix"
WARNING_TYPE_SIZE_EXPECTATION = "Compliant minimum government-warning type size"

# Image-quality gates are tuned for RapidOCR's default detector, whose shortest-side target is
# 736 px. They keep clean studio images on the decode-only path while bounding corrective work.
QUALITY_ANALYSIS_MAX_SIDE_PX = 1000
OCR_MAX_SIDE_PX = 1400
OCR_TARGET_MIN_SIDE_PX = 736
OCR_MAX_UPSCALE_FACTOR = 2.0
# Measured on the 10-core development host across every synthetic benchmark variant. RapidOCR
# calls its 0/180-degree crop classifier `use_cls`; EXIF handling and deskew cover the fixture set.
OCR_USE_ANGLE_CLASSIFIER = False
OCR_INTRA_OP_NUM_THREADS = 6
BLUR_VARIANCE_THRESHOLD = 80.0
MIN_DESKEW_ANGLE_DEGREES = 1.0
MAX_DESKEW_ANGLE_DEGREES = 15.0
MIN_DESKEW_SUPPORTING_LINES = 5
HOUGH_CANNY_LOW_THRESHOLD = 50
HOUGH_CANNY_HIGH_THRESHOLD = 150
HOUGH_MIN_LINE_LENGTH_PX = 20
HOUGH_MIN_LINE_LENGTH_RATIO = 0.08
HOUGH_MAX_LINE_GAP_RATIO = 0.02
CONTRAST_LOW_PERCENTILE = 1.0
CONTRAST_HIGH_PERCENTILE = 99.0
MIN_CONTRAST_RANGE = 80.0
MAX_TILE_ILLUMINATION_SPREAD = 40.0
ILLUMINATION_TILE_ROWS = 4
ILLUMINATION_TILE_COLUMNS = 4
GLARE_LUMINANCE_THRESHOLD = 250
MIN_GLARE_FRACTION = 0.02
MAX_GLARE_FRACTION = 0.45
CLAHE_CLIP_LIMIT = 2.0
CLAHE_TILE_GRID_SIZE = (8, 8)
PERSPECTIVE_MIN_AREA_RATIO = 0.15
PERSPECTIVE_MAX_AREA_RATIO = 0.95
PERSPECTIVE_APPROXIMATION_RATIO = 0.02
PERSPECTIVE_OPPOSITE_SIDE_DELTA = 0.08
PERSPECTIVE_CORNER_COSINE = 0.12
PERSPECTIVE_BORDER_MARGIN_RATIO = 0.01
PERSPECTIVE_MIN_OUTPUT_SIDE_PX = 64
PERSPECTIVE_MAX_OUTPUT_AREA_RATIO = 1.5

# Layout extraction thresholds operate in OCR coordinates and never affect rule verdicts.
OCR_LINE_MIN_VERTICAL_OVERLAP_RATIO = 0.5
OCR_LINE_CENTER_TOLERANCE_RATIO = 0.35
EVIDENCE_CROP_PADDING_PX = 6
WARNING_MAX_LINE_GAP_MULTIPLIER = 3.0
WARNING_FALLBACK_MIN_CUES = 2
BOTTLER_MAX_CONTINUATION_LINES = 3
BOTTLER_MAX_LINE_GAP_MULTIPLIER = 1.5
BRAND_MAX_CHARACTERS = 80
BRAND_AMBIGUITY_HEIGHT_RATIO = 0.9
BRAND_MULTILINE_MAX_GAP_RATIO = 0.5
BRAND_MULTILINE_MIN_HORIZONTAL_OVERLAP_RATIO = 0.5
