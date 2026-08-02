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

**Trade-off taken:** type size is reported as `NOT_EVALUATED` rather than guessed from pixel height. It is never reported as `PASS` and never rendered green. Since 2026-08-01 the check's detail text does surface the 27 CFR 16.22(b) reference tiers (1 mm ≤ 237 mL, 2 mm up to 3 L, 3 mm above, with 40/25/12 characters-per-inch caps) so the agent knows what to verify by eye; the tiers are anchored in `docs/cfr/27-cfr-16-22.txt` and pinned by a provenance test.

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

**Superseded 2026-08-01.** The p50 0.839s above did not reproduce on re-measurement; the same
tool on the same machine under ordinary load reports p50 **1.084s** / p95 **1.511s**, and the
deployed app answers a single label in about **0.9s** wall clock. The requirement still holds
with room to spare, but the figures in [measurements.md](measurements.md) are the current ones
and state their conditions. The lesson kept here deliberately: a latency number without the
machine state beside it is not a measurement.

---

### **OPEN** — real labels lose their inter-word spaces

Found 2026-08-01 by running genuine artwork from the TTB Public COLA Registry through
`verify()`. OCR reads stylised label typography as `GOVERNMENTWARNING:`,
`IMPORTED&BOTTLEDBYSAHALEE` and `Alcohol Content40% by Vol`. Every extraction signal assumed
spaces, so on a real label that plainly stated all three, the government warning, the bottler
and the alcohol content were all reported unevaluated.

Mitigated, not solved:

- Alcohol markers now cover `ALC 40% BY VOL`, `Alcohol Content 40% by Vol` and `40% ABV`.
- The warning anchor and bottling-phrase signals join words with `\s*`.
- The warning comparison has a space-insensitive second pass. It remains exact and
  case-preserving — title case still FAILs — but a match found only that way reports REVIEW,
  never PASS, because the tool cannot distinguish a label that genuinely omits the spaces from
  a reader that dropped them.

Still failing, by design: a full-width OCR substitution such as `）` for `)` fails the warning
comparison, because the warning text is deliberately not Unicode-folded. Folding it would risk
masking a real substitution in the one check that must not be fuzzy. The agent sees the
word-level diff and the crop instead.

### **OPEN** — COLA registry images are composite artwork sheets

A COLA image is not one label. It is the front, the back and often a serving-facts panel laid
side by side on one sheet. Horizontal line grouping therefore merges text across panels, and
the warning check can pick up the bottler's line from the neighbouring panel. Splitting the
same image into single panels reads correctly.

The tool's contract is one label per image. Handling composite sheets would need column
segmentation before line grouping — worth doing before any COLA-fed deployment, out of scope
for a prototype.

---

## Standards-of-fill check — scope decisions (added 2026-08-01)

Net contents are now checked twice: once against the application value, and once for
membership in the federally authorized container sizes (27 CFR 5.203 for spirits, 4.72 for
wine, both as expanded by T.D. TTB-200; anchored in `docs/cfr/` and pinned by provenance
tests). Decisions worth stating:

- **Metric values compare exactly.** `701 mL` fails; no epsilon can absorb it, because the
  regulation authorizes sizes, not neighborhoods. Only fl-oz-stated values get a tolerance
  of half the one-decimal print step (~1.48 mL), so `25.4 fl oz` resolves to 750 mL.
- **A nonstandard reading with an authorized application value is `REVIEW`, not `FAIL`** —
  701-vs-750 is far more likely an OCR misread than a genuinely nonstandard bottle. The
  detail names both values so the agent can decide from the crop.
- **Malt beverages report `NOT_EVALUATED`.** 27 CFR Part 7 sets no standards of fill, so
  there is no check to run, and an unearned green would violate the honesty invariant.
- **Per-class mandatory-field sets and the wine sulfite declaration are not implemented.**
  The application record has no sulfite field, and inventing one exceeds the brief. A wine
  below 7% ABV does get an advisory note (FDA jurisdiction, 27 CFR 4.10 definition) on the
  alcohol check, because that needs no new data.

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
