# Requirements audit against the brief

The brief buries its real constraints inside interview prose, so this is a line-by-line
trace from what a stakeholder actually said to the code that satisfies it and the test
that holds it there. Line numbers refer to `THT-INSTRUCTIONS.md`.

Status key: **Met** — implemented and tested. **Partial** — implemented with a stated
limit. **Scoped out** — the brief excludes it.

## Stakeholder constraints

| # | Requirement (source) | Status | Where | Evidence |
|---|---|---|---|---|
| 1 | "If we can't get results back in about 5 seconds, nobody's going to use it" — Sarah Chen, L19 | **Met** | whole pipeline | Deployed app answers in **1.4s** end to end, measured in a browser; local p50 1.084s / p95 1.511s (`docs/measurements.md`) |
| 2 | "handle batch uploads" of "200, 300 label applications at once" — Sarah Chen, L23 | **Met** | `src/labelcheck/batch.py` | 300 labels in **346s**, 0 errors, peak RSS 1110MB (`tools/bench_batch.py`); progress, time-remaining and stop-preserves-results in `app.py` |
| 3 | "something my mother could figure out", 73-year-old benchmark, "half our team is over 50" — Sarah Chen, L21 | **Met** | `app.py` | One obvious path; 52px touch targets and no horizontal overflow at 360px, verified in-browser; **two clicks** from landing to a result via "Try a sample label" |
| 4 | "our network blocks outbound traffic… firewall blocked connections to their ML endpoints" — Marcus Williams, L39 | **Met** | `src/labelcheck/ocr.py` | No network library imported anywhere in `src/labelcheck/`; RapidOCR ships 3 ONNX files (16.2 MB) inside the wheel, so nothing is fetched at run time |
| 5 | "We're not storing anything sensitive for this exercise" — Marcus Williams, L37 | **Met** | in-memory pipeline | `tests/test_no_disk_persistence.py` statically scans the package and fails on any `imwrite`/`.save(`/`open(...,"w")`/`tempfile` on image data |
| 6 | "not looking to integrate with COLA directly" — Marcus Williams, L35 | **Scoped out** | — | Standalone; application values come from the form or the manifest |
| 7 | "'STONE'S THROW' on the label but 'Stone's Throw' in the application… obviously the same thing. You need judgment." — Dave Morrison, L47 | **Met** | `rules/brand.py` | `tests/test_acceptance.py::test_stones_throw_apostrophe_and_case_variation_passes`; three-state PASS/REVIEW/FAIL exists precisely for this |
| 8 | Warning must be "exact… word-for-word"; "'Government Warning' in title case instead of all caps. Rejected." — Jenny Park, L57 | **Met** | `rules/warning.py` | Normalized exact comparison, never fuzzy; case preserved. `test_title_case_government_warning_prefix_fails`, plus `test_title_case_is_still_failed_even_without_spaces` |
| 9 | Warning "has to be in all caps **and bold**" — Jenny Park, L57 | **Partial** | `rules/warning.py` | Caps is its own sub-check. Boldness is not recoverable from OCR text, so it reports `NOT_EVALUATED` and never renders green. Documented in `docs/limitations.md` |
| 10 | "images that aren't perfectly shot… weird angles… bad lighting… glare" — Jenny Park, L59 | **Met** | `preprocess.py` | Conditional deskew, perspective, CLAHE, upscaling. Rotated/glare/ornate variants read 18/18 fields; a shipped sample is deliberately angled and glared |
| 11 | Statutory warning text | **Met** | `config.py` | Verified character-for-character against GPO and the eCFR versioner API; pinned by `tests/test_warning_provenance.py` |

## Label elements the brief lists (L71–77)

| Element | Rule module | Method |
|---|---|---|
| Brand name | `rules/brand.py` | Normalize, then fuzzy with a REVIEW band |
| Class/type designation | `rules/class_type.py` | Same |
| Alcohol content | `rules/alcohol.py` | Numeric parse against the CFR tolerance for the beverage class; proof cross-checked as 2×ABV |
| Net contents | `rules/net_contents.py` | Unit-normalized numeric compare (`750 mL` == `0.75 L`) |
| Container size (standards of fill) | `rules/net_contents.py::verify_standard_of_fill` | Membership in the authorized 27 CFR 5.203 / 4.72 size lists (T.D. TTB-200, eCFR-verified and provenance-pinned); wine even-liters ≥ 4 L; malt exempt per Part 7 |
| Name and address of bottler/producer | `rules/bottler.py` | Prefix-stripped identity + address compare |
| Country of origin **for imports** | `rules/origin.py` | Conditional on the application record, not unconditional |
| Government Health Warning | `rules/warning.py` | Normalized exact + separate uppercase sub-check + word-level diff |

The brief's own sample label (L87–91: `OLD TOM DISTILLERY` / `Kentucky Straight Bourbon
Whiskey` / `45% Alc./Vol. (90 Proof)` / `750 mL`) is the shipped demo label and the
control fixture. Its ABV/proof cross-check and the `750 mL` vs `0.75 L` case are both
acceptance tests.

## Implicit requirements from the evaluation criteria

| Requirement | Status | Evidence |
|---|---|---|
| Error handling and empty states (bad file type, corrupt image, manifest mismatches) | **Met** | Typed decode errors surface as plain-language retry messages (`preprocess.py`, `app.py`); a corrupt image in a batch becomes one visible problem row, never a crashed run (`batch.py`); manifest↔image mismatches are reported in both directions; `.streamlit/config.toml` keeps tracebacks out of the browser |
| Per-field confidence reporting, not one opaque verdict | **Met** | Every `FieldResult` carries its own status, confidence and crop; the UI renders each field separately and the CSV export preserves them |

## Deliverables (L97–102)

| Item | Status |
|---|---|
| Source repository | https://github.com/junecodetm/ttb-label-check |
| README with setup and run instructions | `README.md` |
| Approach, tools, assumptions documented | `README.md`, `docs/measurements.md`, `docs/limitations.md`, `docs/adr/0001-ocr-engine.md` |
| Deployed application URL | https://ttb-label-check.streamlit.app — verified serving the current build |

## "Create or source additional test labels" (L93)

Both. Synthetic variants are generated deterministically (`tools/make_samples.py`,
`tests/fixture_factory.py`), and real approved artwork was pulled from the TTB Public
COLA Registry. The real labels are what exposed the lost-inter-word-space defect that
the synthetic corpus could never have shown — see `docs/measurements.md`.

## "Document any trade-offs or limitations" (L113)

`docs/limitations.md`, kept current: boldness and type size are `NOT_EVALUATED` rather
than guessed; COLA artwork sheets are composite images whose panels defeat line grouping;
a full-width `）` from OCR still fails the warning comparison by design, because folding
Unicode there could mask a real substitution in the one check that must not be fuzzy.
