# Limitations and trade-offs

The brief asks directly: *"Document any trade-offs or limitations."* This is that document. It is a project deliverable, not internal notes — everything here should be honest enough to hand to an evaluator.

Each formerly unresolved risk below is closed with its result and supporting evidence.

---

## Checks that cannot be fully implemented

### Boldness of the government warning — heuristic or out of scope

Jenny Park's requirement is that `GOVERNMENT WARNING:` appear in all caps **and bold**. The caps check is exact and reliable. Boldness is not recoverable from OCR text output at all — the engine returns characters and boxes, not font weight. Detecting it requires a stroke-width or glyph-thickness heuristic run on the pixels.

**Trade-off taken:** boldness is reported as `NOT_EVALUATED` rather than guessed. It is never reported as `PASS` and never rendered green. An unevaluated check displaying as verified is worse than an absent one.

### Minimum type size — approximation only

TTB sets minimum type sizes by container volume. From an image, type size can only be approximated as bounding-box height relative to image height. That approximation breaks down entirely without a known physical container size — the same label photographed close up and far away yields different numbers.

**Trade-off taken:** type size is reported as `NOT_EVALUATED` rather than guessed from pixel height. It is never reported as `PASS` and never rendered green.

---

## Resolved assumptions

### **CLOSED 2026-07-31** — the statutory warning text is verified against the CFR

The 27 CFR 16.21 text was checked against two independent authoritative sources: the U.S. GPO / govinfo 2024 annual edition and the eCFR versioner API. They agree character for character, and the application constant matches them.

The exact payload and source URLs are anchored in `docs/cfr/27-cfr-16-21.txt`. `tests/test_warning_provenance.py` compares that payload with `src/labelcheck/config.py` byte for byte, so any future drift fails the test suite.

### **CLOSED 2026-07-31** — the OCR engine choice is measured on the fixture corpus

RapidOCR was benchmarked warm on all six deterministic synthetic variants. Semantic field
accuracy counts the six visible values (brand, class/type, alcohol, net contents, bottler, and
government warning) through the production rules; optional domestic origin and the duplicate or
heuristic warning subchecks are excluded.

| Variant | Before normalization fix | Final | Remaining misses |
|---|---:|---:|---|
| Clean control | 6/6 | 6/6 | — |
| Ornate/script | 5/6 | 6/6 | — |
| Rotated | 6/6 | 6/6 | — |
| Glare | 6/6 | 6/6 | — |
| Low resolution | 3/6 | 3/6 | alcohol punctuation, merged bottler words, warning spacing |
| Combined adversarial | 3/6 | 4/6 | alcohol punctuation and warning spacing |

EasyOCR was **deliberately not installed or run**, so this is not a head-to-head speed claim.
EasyOCR brings PyTorch and roughly 800 MB of installed weight against RapidOCR's 16.2 MB of
in-wheel ONNX models. It therefore cannot win the latency and cold-start axis being optimized
without first conflicting with the HuggingFace Spaces free-tier target.

The revisit trigger is accuracy on real photographed labels: if RapidOCR proves inadequate on
stylized typography outside this synthetic corpus, EasyOCR becomes the fallback. The engine
boundary keeps that swap confined to `src/labelcheck/ocr.py`; the rest of the pipeline continues
to consume `TextBlock` values with bounding boxes.

### **CLOSED 2026-07-31** — the 5-second budget is measured

Model startup was excluded after an explicit warm-up. On the clean fixture, the supplied 20-run
baseline from `tools/time_single.py` was p50 **1.003s** / p95 **1.148s**. After optimization, the
same 20-run tool measured p50 **0.803s** / p95 **0.961s**: 19.9% lower at p50 and 16.3% lower at
p95.

The broader 18-sample benchmark (three timed runs across each of six variants) moved from p50
**0.949s** / p95 **1.341s** before changes to p50 **0.839s** / p95 **1.117s** after the final clean
fast-path change. Its final per-stage measurements were:

| Warm stage | p50 | p95 |
|---|---:|---:|
| Decode + preprocess | 0.030s | 0.068s |
| OCR | 0.775s | 1.070s |
| Extraction + rules | 0.016s | 0.022s |
| Pipeline end to end | 0.839s | 1.117s |

The 5-second requirement is met with substantial headroom. These are local macOS arm64 /
CPython 3.11.15 synthetic-fixture results, not a production-hardware or real-photograph SLA.

---

## Deliberate scope boundaries

### No COLA integration

Explicitly out of scope per Marcus Williams: *"that's a whole different beast with its own authorization requirements."* This is a standalone proof of concept. Expected values arrive by typed form (single label) or CSV manifest (batch), not from the COLA system.

### Nothing is persisted

Uploaded images, crops, and extracted text are processed in memory and never written to disk. This satisfies Marcus's PII and document-retention constraint, and is enforced by a static test rather than only by convention.

The cost: no history, no resumable batches, no audit trail. A production version would need all three, and would need the retention policy answered first.

### Synthetic fixtures prove wiring, not real-world accuracy

The test and benchmark fixtures are deterministic synthetic labels rather than real photographed artwork. They prove that upload, preprocessing, OCR, extraction, rules, crops, and reporting are wired together correctly. They do not establish accuracy on real labels; a representative photographed-label corpus is required before making that claim.

### Imperfect photographs degrade, they do not fail

Jenny Park's request for tolerance of weird angles, bad lighting, and glare is implemented as a preprocessing pipeline gated on an image-quality check. It is a stretch goal: an image the pipeline cannot straighten is still OCR'd as-is and reported honestly. Results on such images will be worse, and the tool says so rather than pretending otherwise.

### The tool never rejects

By design, `FAIL` means "an agent should look at this and will almost certainly reject it", not "rejected". Dave Morrison's `STONE'S THROW` / `Stone's Throw` case is the reason: mechanical matching without judgment produces confidently wrong rejections. The three-state model routes ambiguity to a human with the cropped evidence attached.

The cost: the tool cannot claim a fully automated throughput number. That is the correct trade for a compliance context.
