# The government health warning

<!-- No `paths:` frontmatter on purpose. This is the tool's most important check and the
     easiest one to get subtly wrong; it stays in context for every session. -->

Governs `src/labelcheck/rules/warning.py` and the statutory constant in `src/labelcheck/config.py`.

## Exact, never fuzzy

Jenny Park's account is unambiguous: the match is word-for-word, and `Government Warning` in title case is a rejection. She caught exactly that and rejected the label.

Implement as a **normalized exact comparison**:

- Collapse whitespace and repair known OCR artifacts (ligatures, `l`/`1`/`I` confusion, hyphenation at line breaks).
- **Preserve case.** Casefolding here would destroy the check.
- Surface a **word-level diff** so the agent sees precisely what deviates — "warning text does not match" is not an actionable result.
- Separately assert that the `GOVERNMENT WARNING:` prefix is uppercase. This is its own sub-check with its own result, because it is its own rejection reason.

Do not route this field through RapidFuzz. Not at a high threshold, not as a fallback.

## Absence is a failure, not an unevaluated check

The warning is mandatory on every label, so "not located" is itself the violation. When no warning text is found (or nothing survives normalization), the wording check returns `FAIL` with a plain-language explanation covering both readings — the label omits the warning, or the photograph was not readable enough and a clearer image is needed. It must not return `NOT_EVALUATED`: the overall roll-up ignores `NOT_EVALUATED`, and a warning-less label reporting an overall PASS is precisely the failure this tool exists to prevent. The prefix sub-check alone stays `NOT_EVALUATED` in that case; one `FAIL` carries the roll-up.

## The statutory text

Lives in `config.py` as the single source of truth. Per 27 CFR 16.21:

```
GOVERNMENT WARNING: (1) According to the Surgeon General, women should not
drink alcoholic beverages during pregnancy because of the risk of birth
defects. (2) Consumption of alcoholic beverages impairs your ability to
drive a car or operate machinery, and may cause health problems.
```

**This string is reproduced from memory and has not been verified.** A single wrong word would silently invert the tool's most important check — every compliant label would fail, or a non-compliant one would pass, with no visible symptom.

Run `/verify-cfr-text` to diff it against the live CFR. Do this before shipping, and before trusting any test that asserts on warning text.

## Bold and minimum type size — scope honestly

Jenny notes the warning must be bold, and TTB sets minimum type sizes by container volume. Be straight about what is achievable:

- **Boldness is not recoverable** from OCR text output. Detecting it requires a stroke-width or glyph-thickness heuristic on the pixels.
- **Type size** can only be *approximated* from bounding-box height relative to image height, and that approximation breaks down without a known physical container size.

Both must therefore be either an explicitly-labelled heuristic or `NOT_EVALUATED`. Per the invariant in `.claude/rules/verdicts.md`, neither may report `PASS` when it is not actually being evaluated, and neither may render green.

The brief asks for trade-offs to be documented. This is the main one — record the decision in `docs/limitations.md`.
