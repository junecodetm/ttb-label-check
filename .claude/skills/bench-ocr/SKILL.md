---
description: Measure RapidOCR against EasyOCR on real label images and check per-stage timings against the 5-second budget. Use before committing to an OCR engine, when labels read inaccurately on stylized typography, or when verifying the latency requirement.
argument-hint: [fixtures-dir]
allowed-tools: Read, Write, Bash
---

# Benchmark the OCR engine against the budget

The RapidOCR choice in `docs/adr/0001-ocr-engine.md` is reasoned from install size and inference characteristics, **not measured**. So is the 5-second budget in `.claude/rules/performance.md`. This procedure replaces both assumptions with numbers.

Fixtures directory: `$1` if provided, otherwise `tests/fixtures/`.

## Method

**Warm first, then measure.** Load the model and run one throwaway image before timing anything. Model load is excluded from the budget by design because it happens once at startup — including it measures the wrong thing.

**Use at least 10 images, and make them adversarial.** A clean studio shot of a serif label proves nothing. The set must include:
- an ornate or script-font distillery label (the predicted RapidOCR weak spot)
- a curved label photographed on a round bottle
- a poorly-lit or glared photograph
- a low-resolution mobile upload
- at least one clean control image

**Time the stages separately**, matching the budget table: decode + preprocess, OCR, extraction + rules. A single end-to-end number cannot tell you which stage to fix.

**Report p50 and p95, not the mean.** Sarah's agents abandoned the vendor tool over its worst case, not its average. A 1.2s mean with a 6s p95 fails the requirement.

**Measure accuracy, not just latency.** For each image, record how many of the six fields were extracted correctly. An engine that is twice as fast and misreads the brand name is not the faster engine — it is the wrong one. Latency alone is the trap this benchmark exists to avoid.

## Compare

Run the identical fixture set through both RapidOCR and EasyOCR. Report side by side:

| | RapidOCR | EasyOCR |
|---|---|---|
| Field accuracy (correct / total) | | |
| Field accuracy, stylized subset | | |
| OCR p50 / p95 | | |
| End-to-end p50 / p95 | | |
| Install size | | |
| Cold start | | |

## Decision rule

- RapidOCR meets the budget and matches EasyOCR's field accuracy → keep it, record the measured numbers.
- RapidOCR is materially worse on stylized typography → **fall back to EasyOCR and re-derive the budget honestly.** Do not keep the faster engine and quietly accept worse reads; do not keep the accurate engine and quietly miss 5s. Whichever way it goes, the number that ships is the measured one.
- Neither meets the budget → say so plainly and surface it as a scope decision. The brief prefers a working core application over an ambitious incomplete one.

## Output

Write the results table and the decision into `docs/limitations.md`, replacing the "unbenchmarked" entry. Update `docs/adr/0001-ocr-engine.md` status from *Proposed* to *Accepted* or *Superseded*, and update the budget table in `.claude/rules/performance.md` if the measured figures differ from the estimates.
