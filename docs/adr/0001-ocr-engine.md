# ADR 0001 — OCR engine: RapidOCR over EasyOCR

**Status:** Proposed — reasoned, not yet benchmarked. Run `/bench-ocr` to accept or supersede.
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

**RapidOCR** — PP-OCR models on ONNX Runtime. Same offline property. Models are roughly 15MB. ONNX Runtime CPU inference is materially faster per image than torch CPU for this class of model.

**Tesseract** — smallest and most established, but degrades badly on decorative typography. Alcohol labels are ornate by nature: script fonts, heavy serifs, text curved around a bottle. Poor fit for either role.

## Decision

Use RapidOCR.

1. **Cold start.** On the free tier, ~800MB of PyTorch against ~15MB of ONNX models is the difference between a workable build and a build or startup timeout. Weights are baked in at build time either way, but the size difference determines whether that build succeeds.
2. **Latency headroom.** Faster CPU inference per image is where the margin for the 5s budget comes from, and it is what makes a 300-label batch tractable rather than theoretical.
3. **The firewall constraint is satisfied by both**, so it does not discriminate. Latency and deployment do.

Tesseract is rejected on accuracy grounds for this specific typography.

The rest of the stack follows `RESOURCES.md` unchanged: Python 3.11+, OpenCV (`opencv-python-headless`), RapidFuzz, Pandas, Streamlit, HuggingFace Spaces. OCR is the only departure.

## First measurements (2026-07-31)

Partial verification of the reasoning above, on macOS arm64 / CPython 3.11.15:

| Claim | Status |
|---|---|
| RapidOCR models are ~15MB | **Confirmed** — 3 ONNX files, 16.2 MB, shipped inside the wheel |
| No runtime weight download | **Confirmed** for the default config — `pip install` is sufficient |
| Model load is cheap enough to cache once | **Confirmed** — 0.19s |
| Faster than EasyOCR per image | **Not tested** — EasyOCR was never installed or run |
| Accurate on ornate typography | **Not tested** — only a synthetic single-line image was read |

Inference on that synthetic image was 1.05s against a 1.5s OCR budget. That is a warning sign rather than a pass: the image was trivial, and a real label is harder.

## What this decision is not

**It is not benchmarked.** The reasoning above is from install size and known inference characteristics, not from running both engines on real label images. The likely failure case is accuracy: RapidOCR may read stylized or ornate distillery typography — script fonts, curved text, heavy serifs — worse than EasyOCR does.

**Fallback trigger:** if `/bench-ocr` shows materially worse field-extraction accuracy on the stylized subset, revert to EasyOCR and re-derive the latency budget from the measured figures. Do not keep the faster engine with worse reads, and do not keep the accurate engine while quietly missing 5s. The number that ships is the measured one.

## Consequences

- Nothing outside `src/labelcheck/ocr.py` imports the engine, so the fallback is a single-file change.
- The wrapper returns `TextBlock[]` with bounding boxes regardless of engine, so the UI evidence crops and type-size heuristics survive a swap.
- `docs/limitations.md` carries an open entry until `/bench-ocr` has run.
