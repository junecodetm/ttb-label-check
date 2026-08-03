# Verdicts and per-field matching

<!-- No `paths:` frontmatter on purpose. This rule governs the shape of every result the
     tool produces, so it must be in context regardless of which file is open. -->

Governs `src/labelcheck/models.py`, everything under `src/labelcheck/rules/`, and how `app.py` renders results.

## Three states: PASS / REVIEW / FAIL

This is the central design decision, and it resolves a real conflict between two stakeholders. Sarah wants agents freed from mechanical matching; Dave insists the work needs judgment and points at `STONE'S THROW` vs `Stone's Throw`. A binary pass/fail forces a bad choice — either it auto-rejects Dave's example, or it loosens thresholds until genuine mismatches slip through.

Three states dissolve the conflict: the tool clears unambiguous matches, flags unambiguous violations, and routes everything in between to a human **with evidence attached**.

**The tool never issues a final rejection on its own.** `FAIL` means "an agent should look at this and will almost certainly reject it", not "rejected".

## The `FieldResult` payload

Every `FieldResult` carries all five of these. A result missing the crop is not renderable, because the crop is the entire trust mechanism:

| Field | Purpose |
|---|---|
| `status` | `PASS` / `REVIEW` / `FAIL` / `NOT_EVALUATED` |
| `expected` | the value from the application record |
| `extracted` | the value read off the label |
| `confidence` | score from the matcher, not from OCR alone |
| `crop` | the bounding-box region the value was read from |

## Never `PASS` a check you did not evaluate

`NOT_EVALUATED` exists because of the bold and type-size checks (see `.claude/rules/government-warning.md`), but the invariant is general: **if a check did not actually run, or ran only as an acknowledged heuristic, it must not report `PASS` and must not render green.** An unevaluated check displaying as green is worse than an absent one — it tells an agent something was verified when nothing was.

The same applies when OCR fails to locate a field at all. That is `NOT_EVALUATED` or `REVIEW`, never `PASS`, and never a silent omission from the report. The government warning is the one exception, in the strict direction: it is mandatory on every label, so absence is itself the violation — a warning that cannot be located is a `FAIL`, not `NOT_EVALUATED`. The roll-up ignores `NOT_EVALUATED`, and a warning-less label must never report an overall PASS (see `.claude/rules/government-warning.md`).

## Never one global fuzzy score

Different fields fail in different ways, so a single similarity ratio across the whole label is wrong. One rule module per field, each returning its own `FieldResult`.

| Field | Method |
|---|---|
| **Brand name**, **class/type** | Normalize (casefold, strip punctuation and apostrophes, collapse whitespace, drop legal suffixes like `LLC`/`INC`), then RapidFuzz `token_sort_ratio`. High → `PASS`, middle band → `REVIEW`, low → `FAIL`. |
| **Alcohol content** | Parse numerically with a regex; compare against the TTB tolerance for the beverage class, never by string equality. Cross-check internal consistency: stated proof should equal 2 × ABV (`45% Alc./Vol. (90 Proof)`). |
| **Net contents** | Unit-normalize (mL / L / fl oz) and compare as numbers. `750 mL` and `0.75 L` are the same value. |
| **Bottler name/address** | Normalize with `normalize_bottler_text` (strip `BOTTLED BY`-style prefixes, casefold, collapse whitespace), then RapidFuzz `token_sort_ratio` with the same REVIEW band as brand. |
| **Country of origin** | Required for imports only — conditional on the application record, not unconditional. |
| **Government warning** | Normalized *exact* comparison. Never fuzzy. See `.claude/rules/government-warning.md`. |

Tune the brand band so `STONE'S THROW` vs `Stone's Throw` lands on `PASS`. That case is an acceptance criterion, not an example.

## Constants are sourced, not guessed

Thresholds, bands, and TTB tolerances live in `config.py`, never inline in a rule module.

The ABV tolerances in particular vary by beverage class and are set by regulation. **Cite the CFR section next to each value when you add it.** Do not fill them in from memory — the same failure mode the government warning text carries, applied to a number that decides pass/fail.

## Normalization belongs in `normalize.py`

Rule modules compare; they do not transform. If you are writing a casefold, a punctuation strip, or a unit conversion inside `rules/`, it belongs in `normalize.py` where it can be tested once and reused. This is what makes the domain logic testable without OCR.
