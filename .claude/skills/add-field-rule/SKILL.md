---
description: Scaffold a new per-field verification rule in src/labelcheck/rules/ with its normalization helpers and pytest cases, following the FieldResult contract. Use when adding a label field to verify.
argument-hint: [field-name]
---

# Add a per-field verification rule

Every field gets its own module. There is no global fuzzy score, and there is no shared "compare two strings" helper that all fields route through — different fields fail in different ways, which is the whole reason for the per-field design.

Field to add: `$1`

## The shape

1. **`src/labelcheck/rules/<field>.py`** — one public function taking the extracted candidate and the expected value from the `ApplicationRecord`, returning a `FieldResult`. It compares; it does not transform and it does not decide policy.

2. **Constants go in `config.py`.** Thresholds, bands, tolerances, unit tables. Never inline in the rule module, never a magic number in a comparison. If the value comes from regulation, cite the CFR section beside it — and source it rather than recalling it.

3. **Normalization goes in `normalize.py`.** Casefolding, punctuation stripping, unit conversion, number parsing. If the rule module contains a `.lower()` or a regex substitution, it is in the wrong file. This is what keeps the rules testable as pure comparisons.

4. **Register it in `pipeline.py`** so `verify()` runs it and the result lands in `LabelReport`. A rule that exists but is not wired in is worse than absent — it looks done.

5. **Decide the field's conditionality.** Some fields only apply in some cases: country of origin is required for imports only. If the field does not apply to this application, the result is `NOT_EVALUATED`, never `PASS`.

## Choosing the comparison

- Text identity where humans would accept variation → normalize, then RapidFuzz `token_sort_ratio`, with a `REVIEW` band between the `PASS` and `FAIL` thresholds.
- Numeric or dimensional → parse to a number and compare with a tolerance. Never compare formatted strings.
- Statutory or verbatim text → normalized exact comparison with a word-level diff. Never fuzzy.

## Tests

In `tests/test_<field>.py`, minimum four cases:

- an exact match → `PASS`
- a cosmetic variation a human would accept → `PASS` (this is the Dave Morrison case for whichever field you are writing)
- a genuine near-miss → `REVIEW`
- a real mismatch → `FAIL`

Pure functions only — no OCR, no images, no `@pytest.mark.slow`. If testing this rule requires an image, the logic is in the wrong layer.

## Before finishing

Re-read `.claude/rules/verdicts.md` and confirm: the `FieldResult` carries all five members including the crop, nothing unevaluated reports `PASS`, and no threshold was hardcoded in the rule module.
