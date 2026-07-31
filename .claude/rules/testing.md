---
paths:
  - "tests/**/*.py"
---

# Testing

## Test the pure functions exhaustively

The substantive logic lives in `normalize.py` and `rules/`, which are pure functions over strings and numbers. That is where correctness is actually decided and where tests are cheap — no OCR, no images, no fixtures, millisecond runtimes.

Everything upstream of them (preprocess, OCR) is expensive to test and mostly not where bugs that matter live.

## The acceptance criteria are the stakeholder anecdotes

These five are requirements in disguise. Every one traces to a named person in the brief:

| Case | Expected | Source |
|---|---|---|
| `STONE'S THROW` vs `Stone's Throw` | `PASS` | Dave Morrison |
| `Government Warning:` in title case | `FAIL` | Jenny Park |
| Warning with altered or omitted wording | `FAIL`, with the diff identifying the deviation | Jenny Park |
| `45% Alc./Vol. (90 Proof)` | proof/ABV cross-check passes | sample label |
| `45% Alc./Vol. (80 Proof)` | flagged | derived |
| `750 mL` vs `0.75 L` | `PASS` | unit normalization |

Add a `REVIEW`-band case for every fuzzy-matched field. A rule tested only at `PASS` and `FAIL` has never exercised the band that the whole three-state design exists for.

## Enforce "store nothing sensitive" mechanically

Marcus's constraint is a hard requirement, and a written instruction is not enforcement. Add a static test that scans `src/labelcheck/` and fails if it finds a disk-write call — `cv2.imwrite`, PIL `.save(`, `open(..., "w")`/`"wb"`, `tempfile` usage on image data.

Grep or AST-walk, either is fine. The point is that the constraint has a red test attached to it rather than living only in prose.

## Fast suite stays fast

Mark end-to-end OCR tests `@pytest.mark.slow` so `pytest -m "not slow"` remains the loop you run constantly.

Test images belong in `tests/fixtures/`. The brief notes that AI image generation works well for producing additional test labels — generate ones that stress the actual failure cases: ornate script typography, curved text on a bottle, glare, a photograph shot at an angle.

## Do not assert on unverified constants

Tests that assert against the government warning text are only as correct as the constant in `config.py`, which has not yet been checked against the CFR. Run `/verify-cfr-text` before treating a green warning test as meaningful — otherwise the suite confirms the tool matches a string that may itself be wrong.
