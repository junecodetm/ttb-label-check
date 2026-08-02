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
# Longest sequences first, for the same first-match-wins reason as the bottler list.
ORIGIN_PREFIX_TOKEN_SEQUENCES = (
    ("country", "of", "origin"),
    ("product", "of", "the"),
    ("produce", "of"),
    ("product", "of"),
    ("imported", "from"),
    ("bottled", "in"),
    ("distilled", "in"),
    ("produced", "in"),
    ("brewed", "in"),
    ("vinted", "in"),
    ("grown", "in"),
    ("made", "in"),
    ("origin",),
)
# Whole-cell agent-entered no-value markers, compared after Unicode/case/whitespace cleanup.
ORIGIN_PLACEHOLDER_VALUES = frozenset(
    ("n/a", "na", "none", "-", "--", r"n\a", "not applicable", "domestic")
)
# Longest sequences first: `normalize_bottler_text` strips the first match, so
# "produced and bottled by" must be tried before the "bottled by" it contains.
BOTTLER_PREFIX_TOKEN_SEQUENCES = (
    ("blended", "and", "bottled", "by"),
    ("brewed", "and", "bottled", "by"),
    ("brewed", "and", "canned", "by"),
    ("distilled", "and", "bottled", "by"),
    ("produced", "and", "bottled", "by"),
    ("cellared", "and", "bottled", "by"),
    ("vinted", "and", "bottled", "by"),
    ("imported", "and", "bottled", "by"),
    ("bottled", "by"),
    ("bottled", "for"),
    ("brewed", "by"),
    ("brewed", "for"),
    ("blended", "by"),
    ("canned", "by"),
    ("canned", "for"),
    ("cellared", "by"),
    ("distilled", "by"),
    ("imported", "by"),
    ("manufactured", "by"),
    ("packaged", "by"),
    ("packaged", "for"),
    ("prepared", "by"),
    ("produced", "by"),
    ("produced", "for"),
    ("vinted", "by"),
    ("made", "by"),
)
FUZZY_UNICODE_NORMALIZATION_FORM = "NFKC"
APOSTROPHE_CHARACTERS = frozenset(("'", "’", "ʼ"))

NUMBER_PATTERN = r"(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.[0-9]+)?|\.[0-9]+"
NUMBER_CANDIDATE_PATTERN = r"[+-]?(?:[0-9][0-9.,]*|\.[0-9][0-9.,]*)"
# Real labels state alcohol content many ways: "45% Alc./Vol.", "ALC 40% BY VOL",
# "Alcohol Content 40% by Vol", "5.5% ABV". Measured against TTB COLA registry
# artwork, matching only the "alc/vol" form left the field unevaluated on labels
# that plainly stated it. Separators are \s* rather than \s+ because OCR routinely
# loses inter-word spaces on stylised label typography.
# Every alternative is CONTIGUOUS and uses at most a single optional space between
# tokens. An earlier version chained `\s*` around optional groups, which made a failed
# match backtrack super-linearly: "ALC" + 2000 spaces + "X" took 9.8s, and that string
# can arrive in a manifest cell. Keep each branch anchored to a literal sequence.
#
# A bare "by volume" is deliberately NOT a marker. It matches juice-content and
# nutrition panels -- "GRAPE JUICE 100% BY VOLUME" parsed as 100% alcohol -- and an
# unevaluated field an agent reviews beats a confident wrong number.
ABV_MARKER_PATTERN = (
    # \b after vol is load-bearing: without it "45% Alc/Volcano" reads as 45% alcohol.
    r"(?:\balc(?:ohol)?\.? ?/ ?vol(?:ume)?\b\.?"
    r"|\balc(?:ohol)?\.? ?by ?vol(?:ume)?\b\.?"
    # No trailing \b: OCR joins the marker to the number ("Alcohol Content40%"), and a
    # word boundary cannot hold between a letter and a digit.
    r"|\balcohol ?content"
    r"|\babv)"
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
# Proof is defined as exactly twice the alcohol-by-volume percentage (27 CFR 5.1:
# "The ethyl alcohol content of a liquid at 60 degrees Fahrenheit, stated as twice
# the percentage of ethyl alcohol by volume."), so the printed proof and ABV should
# agree exactly. This tolerance is the proof-space image of the +/-0.3 percentage
# point ABV tolerance in 27 CFR 5.65, and it also absorbs the whole-number rounding
# labels conventionally apply to the printed proof.
PROOF_ABV_TOLERANCE = Decimal("0.6")  # 2 x the 0.3-point ABV tolerance, 27 CFR 5.65

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

# 27 CFR 4.10 defines "wine" for FAA Act labeling purposes as containing "not less than
# 7 percent and not more than 24 percent of alcohol by volume" (verified against the eCFR
# versioner API, title-27 issue 2026-07-30). Below 7% the TTB labeling rules in Part 4 do
# not apply and FDA food-labeling rules govern instead, so the alcohol rule attaches an
# advisory note — a TTB reviewer would not process such a label under a wine COLA.
WINE_FDA_JURISDICTION_MIN_ABV = Decimal("7")


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


# Class/type designation vocabulary, used only to pick which ABV tolerance applies.
# `canonical_beverage_class` resolves ties by longest keyword, so compound terms such
# as "barley wine" (a malt beverage) correctly outrank the bare "wine".
#
# A term is listed only where the category is unambiguous. Hard seltzer and hard
# lemonade are deliberately absent: their base alcohol is not determinable from the
# class wording, so they resolve to no class and the alcohol rule routes them to
# REVIEW rather than silently applying the wrong statutory tolerance.
#
# Note a limit of substring matching: "wine cooler" resolves to wine because it
# contains the word, though such products are often malt-based. Excluding it would
# need a negative-term mechanism this table does not have.
BEVERAGE_CLASS_KEYWORDS = (
    (
        # Malt beverage class designations, 27 CFR 7.142-7.145.
        "beer",
        (
            "beer",
            "ale",
            "lager",
            "lager beer",
            "malt beverage",
            "malt liquor",
            "barley wine",
            "porter",
            "stout",
            "pilsner",
            "pilsener",
            "bock",
            "flavored malt beverage",
            "cereal beverage",
            "near beer",
        ),
    ),
    (
        # Wine classes and types, 27 CFR 4.21; semi-generic names, 27 CFR 4.24.
        # Cider, perry, mead (honey wine) and sake are agricultural wines under
        # 27 CFR 4.21(e)-(f); sake is named there explicitly.
        "wine",
        (
            "wine",
            "grape wine",
            "table wine",
            "light wine",
            "dessert wine",
            "sparkling wine",
            "carbonated wine",
            "citrus wine",
            "fruit wine",
            "agricultural wine",
            "honey wine",
            "mead",
            "rice wine",
            "sake",
            "saké",
            "cider",
            "hard cider",
            "perry",
            "aperitif wine",
            "vermouth",
            "retsina",
            "sangria",
            # Semi-generic geographic designations, 27 CFR 4.24(b)(2).
            "angelica",
            "burgundy",
            "claret",
            "chablis",
            "champagne",
            "chianti",
            "malaga",
            "marsala",
            "madeira",
            "moselle",
            "port",
            "rhine wine",
            "hock",
            "sauterne",
            "haut sauterne",
            "sherry",
            "tokay",
            # Common varietal designations, 27 CFR 4.23.
            "cabernet",
            "merlot",
            "chardonnay",
            "pinot",
            "riesling",
            "sauvignon",
            "zinfandel",
            "syrah",
            "shiraz",
            "malbec",
            "tempranillo",
            "sangiovese",
            "grenache",
            "viognier",
            "moscato",
            "muscat",
            "prosecco",
            "rose wine",
            "blush wine",
        ),
    ),
    (
        # Distilled spirits classes, 27 CFR 5.141-5.156. The 27 CFR 5.65 tolerance
        # applies to every distilled spirits product, so specialty products under
        # 27 CFR 5.156 take the same figure as the named classes.
        "distilled_spirits",
        (
            "distilled spirits",
            "distilled spirit",
            "spirits",
            "spirit",
            "neutral spirits",
            "grain spirits",
            "whiskey",
            "whisky",
            "bourbon",
            "rye whiskey",
            "rye whisky",
            "corn whiskey",
            "corn whisky",
            "malt whiskey",
            "malt whisky",
            "single malt",
            "light whiskey",
            "light whisky",
            "scotch",
            "vodka",
            "gin",
            "genever",
            "sloe gin",
            "rum",
            "cachaca",
            "cachaça",
            "brandy",
            "cognac",
            "armagnac",
            "grappa",
            "pisco",
            "applejack",
            "kirschwasser",
            "slivovitz",
            "agave spirits",
            "tequila",
            "mezcal",
            "mescal",
            "cordial",
            "liqueur",
            "creme de",
            "crème de",
            "schnapps",
            "absinthe",
            "aquavit",
            "akvavit",
            "soju",
            "baijiu",
            "shochu",
            "moonshine",
            "flavored spirits",
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

# Standards of fill (authorized container sizes). Values verified against the eCFR
# versioner API on 2026-08-01 (title-27 issue date 2026-07-30); plain-text provenance
# extracts live in docs/cfr/27-cfr-5-203.txt and docs/cfr/27-cfr-4-72.txt, and
# tests/test_standard_of_fill.py pins these sets against those anchors.
#
# Distilled spirits — 27 CFR 5.203(a), as amended by T.D. TTB-200 ("Standards of Fill
# for Wine and Distilled Spirits", 90 FR 1876, Jan. 10, 2025), which expanded the list
# (700/720/900/945 mL among the additions). 25 authorized metric sizes.
SPIRITS_STANDARDS_OF_FILL_ML = frozenset(
    Decimal(value)
    for value in (
        "3750",
        "3000",
        "2000",
        "1800",
        "1750",
        "1500",
        "1000",
        "945",
        "900",
        "750",
        "720",
        "710",
        "700",
        "570",
        "500",
        "475",
        "375",
        "355",
        "350",
        "331",
        "250",
        "200",
        "187",
        "100",
        "50",
    )
)
# Wine — 27 CFR 4.72(a), as amended by T.D. TTB-200 (90 FR 1875, Jan. 20, 2025).
WINE_STANDARDS_OF_FILL_ML = frozenset(
    Decimal(value)
    for value in (
        "3000",
        "2250",
        "1800",
        "1500",
        "1000",
        "750",
        "720",
        "700",
        "620",
        "600",
        "568",
        "550",
        "500",
        "473",
        "375",
        "360",
        "355",
        "330",
        "300",
        "250",
        "200",
        "187",
        "180",
        "100",
        "50",
    )
)
# 27 CFR 4.72(b): wine containers of 4 liters or larger are authorized when filled and
# labeled in even (whole) liters — 4 L, 5 L, 6 L, and so on.
WINE_LARGE_FORMAT_MIN_ML = Decimal("4000")
WINE_LARGE_FORMAT_STEP_ML = MILLILITERS_PER_LITER
# Malt beverages are deliberately absent from this map: 27 CFR Part 7 prescribes no
# standards of fill, so no membership check exists to run and the rule reports
# NOT_EVALUATED for beer rather than an unearned PASS.
STANDARDS_OF_FILL_ML = {
    "distilled_spirits": SPIRITS_STANDARDS_OF_FILL_ML,
    "wine": WINE_STANDARDS_OF_FILL_ML,
}
# Half of the one-decimal fl-oz print step (0.05 fl oz ~= 1.479 mL): a label stating
# "25.4 fl oz" resolves to the 750 mL standard (raw conversion 751.17 mL). Applies ONLY
# to fl-oz-stated values; metric-stated values compare exactly, so 701 mL is never
# silently absorbed into 700 mL.
STANDARD_OF_FILL_FL_OZ_TOLERANCE_ML = FLUID_OUNCE_TO_ML * Decimal("0.05")

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
# 27 CFR 16.22(b) minimum warning type size by container volume, paired with the
# 16.22(a)(4) maximum characters per inch for each tier (verified against the eCFR
# versioner API, title-27 issue 2026-07-30). Reference metadata only: a flat photograph
# carries no physical scale, so the type-size check stays NOT_EVALUATED and cites this
# table in its detail text instead of guessing (.claude/rules/government-warning.md).
# Rows: (container volume ceiling in mL, or None for unbounded; min type size in mm;
# max characters per inch).
WARNING_TYPE_SIZE_TABLE = (
    (Decimal("237"), 1, 40),
    (Decimal("3000"), 2, 25),
    (None, 3, 12),
)

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

# A country of origin wraps onto at most one continuation line in practice
# ("PRODUCT OF" above the country name), so allow less drift than a bottler address.
ORIGIN_MAX_CONTINUATION_LINES = 1
ORIGIN_MAX_LINE_GAP_MULTIPLIER = 1.5

# Pillow's own decompression-bomb ceiling. Larger than any real label photograph,
# small enough that a hostile or corrupt file cannot exhaust memory before decoding.
MAX_IMAGE_PIXELS = 80_000_000
BRAND_MAX_CHARACTERS = 80
BRAND_AMBIGUITY_HEIGHT_RATIO = 0.9
BRAND_MULTILINE_MAX_GAP_RATIO = 0.5
BRAND_MULTILINE_MIN_HORIZONTAL_OVERLAP_RATIO = 0.5
