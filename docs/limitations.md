# Limitations and trade-offs

The brief asks directly: *"Document any trade-offs or limitations."* This is that document. It is a project deliverable, not internal notes — everything here should be honest enough to hand to an evaluator.

Entries marked **OPEN** are unresolved risks, not accepted trade-offs. They have a named discharge procedure.

---

## Checks that cannot be fully implemented

### Boldness of the government warning — heuristic or out of scope

Jenny Park's requirement is that `GOVERNMENT WARNING:` appear in all caps **and bold**. The caps check is exact and reliable. Boldness is not recoverable from OCR text output at all — the engine returns characters and boxes, not font weight. Detecting it requires a stroke-width or glyph-thickness heuristic run on the pixels.

**Trade-off taken:** implement it as an explicitly-labelled heuristic, or report `NOT_EVALUATED`. It is never reported as `PASS` and never rendered green. An unevaluated check displaying as verified is worse than an absent one.

### Minimum type size — approximation only

TTB sets minimum type sizes by container volume. From an image, type size can only be approximated as bounding-box height relative to image height. That approximation breaks down entirely without a known physical container size — the same label photographed close up and far away yields different numbers.

**Trade-off taken:** same treatment as boldness. Approximate and label it as such, or `NOT_EVALUATED`. Never a silent green.

---

## Unverified assumptions

### **OPEN** — the statutory warning text has not been checked against the CFR

The 27 CFR 16.21 text in `src/labelcheck/config.py` is reproduced from memory. A single wrong word silently inverts the tool's most important check, with no visible symptom in either direction.

**Discharge:** run `/verify-cfr-text`. Until then, a passing warning test only proves the tool matches a string that may itself be wrong.

### **OPEN** — the OCR engine choice is reasoned, not measured

RapidOCR was chosen over EasyOCR on install size and inference characteristics. See `docs/adr/0001-ocr-engine.md`. The predicted weak spot is accuracy on ornate distillery typography.

**Discharge:** run `/bench-ocr`.

### **OPEN** — the 5-second budget is inherited, not measured

The per-stage budget in `.claude/rules/performance.md` is a target derived from Sarah Chen's requirement, not from timing this application. No latency figure in this repository has been measured.

**Discharge:** run `/bench-ocr`, then replace the estimates with p50 and p95 figures.

---

## Deliberate scope boundaries

### No COLA integration

Explicitly out of scope per Marcus Williams: *"that's a whole different beast with its own authorization requirements."* This is a standalone proof of concept. Expected values arrive by typed form (single label) or CSV manifest (batch), not from the COLA system.

### Nothing is persisted

Uploaded images, crops, and extracted text are processed in memory and never written to disk. This satisfies Marcus's PII and document-retention constraint, and is enforced by a static test rather than only by convention.

The cost: no history, no resumable batches, no audit trail. A production version would need all three, and would need the retention policy answered first.

### Imperfect photographs degrade, they do not fail

Jenny Park's request for tolerance of weird angles, bad lighting, and glare is implemented as a preprocessing pipeline gated on an image-quality check. It is a stretch goal: an image the pipeline cannot straighten is still OCR'd as-is and reported honestly. Results on such images will be worse, and the tool says so rather than pretending otherwise.

### The tool never rejects

By design, `FAIL` means "an agent should look at this and will almost certainly reject it", not "rejected". Dave Morrison's `STONE'S THROW` / `Stone's Throw` case is the reason: mechanical matching without judgment produces confidently wrong rejections. The three-state model routes ambiguity to a human with the cropped evidence attached.

The cost: the tool cannot claim a fully automated throughput number. That is the correct trade for a compliance context.
