# ADR 0001 — OCR engine: RapidOCR over EasyOCR

**Status:** Accepted — verified on the six-variant synthetic benchmark corpus.
**Date:** 2026-07-31
**Supersedes:** the EasyOCR recommendation in `RESOURCES.md`

## Context

Two requirements from the brief constrain this choice, and they are the two hardest to satisfy together:

- **< 5 seconds per label, end to end.** Sarah Chen's scanning-vendor pilot took 30-40s and agents abandoned it. This governs every stack decision.
- **No dependency on outbound cloud APIs.** Marcus Williams: the federal firewall blocked the vendor's ML endpoints, so half their features never worked. The verification path must run fully local.

Deployment is HuggingFace Spaces free tier, which sleeps after inactivity and has a bounded build environment.

`RESOURCES.md` recommends EasyOCR. It satisfies the offline constraint but is worth re-examining against the latency and deployment constraints, which is where the recommendation was not tested.

## Options

**EasyOCR** — runs locally, no API keys, good accuracy on general text. Pulls in PyTorch, roughly 800MB installed. CPU inference goes through the torch path.

**RapidOCR** — PP-OCR models on ONNX Runtime. Same offline property. Models are roughly 15MB,
and the CPU path does not require the PyTorch runtime.

**Tesseract** — smallest and most established, but degrades badly on decorative typography. Alcohol labels are ornate by nature: script fonts, heavy serifs, text curved around a bottle. Poor fit for either role.

## Decision

Use RapidOCR.

1. **Cold start.** On the free tier, ~800MB of PyTorch against ~15MB of ONNX models is the difference between a workable build and a build or startup timeout. Weights are baked in at build time either way, but the size difference determines whether that build succeeds.
2. **Latency headroom.** RapidOCR now measures comfortably inside the 5s budget. Avoiding the
   roughly 800 MB PyTorch dependency also protects build and cold-start latency on the sleeping
   free tier; no unrun EasyOCR per-image comparison is needed to establish those deployment costs.
3. **The firewall constraint is satisfied by both**, so it does not discriminate. Latency and deployment do.

Tesseract is rejected on accuracy grounds for this specific typography.

The rest of the stack follows `RESOURCES.md` unchanged: Python 3.11+, OpenCV (`opencv-python-headless`), RapidFuzz, Pandas, Streamlit, HuggingFace Spaces. OCR is the only departure.

## Measurements (2026-07-31)

Measured on macOS arm64 / CPython 3.11.15 after warming the process singleton. The supplied
20-run clean-fixture baseline was p50 **1.003s** / p95 **1.148s** end to end. The optimized
pipeline measured p50 **0.803s** / p95 **0.961s** on the same tool.

The six-variant benchmark used 18 timed samples and measured p50 **0.839s** / p95 **1.117s** end
to end after optimization:

| Warm stage | p50 | p95 |
|---|---:|---:|
| Decode + preprocess | 0.030s | 0.068s |
| OCR | 0.775s | 1.070s |
| Extraction + rules | 0.016s | 0.022s |
| Pipeline end to end | 0.839s | 1.117s |

Semantic field accuracy after the brand space-loss normalization fix was:

| Clean | Ornate/script | Rotated | Glare | Low resolution | Combined adversarial |
|---:|---:|---:|---:|---:|---:|
| 6/6 | 6/6 | 6/6 | 6/6 | 3/6 | 4/6 |

The low-resolution misses are documented rather than hidden: OCR drops alcohol punctuation,
merges bottler words, and loses government-warning spacing. The combined case retains the
bottler but still misses alcohol punctuation and warning spacing.

RapidOCR's three packaged models total 16.2 MB, require no runtime download, and loaded in 0.19s
in the earlier cold probe. EasyOCR was **deliberately not installed or run**, so this ADR makes no
head-to-head inference claim. Its PyTorch-based roughly 800 MB footprint and cold-start cost
conflict with the HuggingFace Spaces free-tier target and cannot improve the latency axis under
decision here.

## Validation boundary and fallback

The benchmark uses deterministic synthetic fixtures, not a representative field corpus of curved
and photographed bottles. The decision is accepted for the current prototype because it meets the
latency budget, reads every semantic field on clean, ornate, rotated, and glare variants, and keeps
the deployment artifact small and fully offline.

**Fallback trigger:** if RapidOCR's accuracy on stylized typography proves inadequate on real
photographed labels, EasyOCR becomes the fallback and `src/labelcheck/ocr.py` is the only engine
file that changes. Re-derive the latency budget from that engine's measured figures rather than
quietly accepting either slower inference or worse reads.

## Consequences

- Nothing outside `src/labelcheck/ocr.py` imports the engine, so the fallback is a single-file change.
- The wrapper returns `TextBlock[]` with bounding boxes regardless of engine, so the UI evidence crops and type-size heuristics survive a swap.
- `docs/limitations.md` records the measured latency and the remaining adverse-fixture misses.
