---
paths:
  - "src/labelcheck/pipeline.py"
  - "src/labelcheck/ocr.py"
  - "src/labelcheck/preprocess.py"
  - "src/labelcheck/batch.py"
  - "app.py"
---

# Performance budget

<!-- Scoped to the hot path only. normalize.py and rules/ are pure string and number work
     at ~100ms for the whole set; the budget is not won or lost there. -->

The 5-second figure is a requirement inherited from the brief, not a measured result. Sarah's scanning-vendor pilot took 30-40s per label and agents abandoned it — *"If we can't get results back in about 5 seconds, nobody's going to use it."*

Treat it as a budget to design against, then verify by measurement with `/bench-ocr`.

| Stage (warm, 18 samples across six variants) | Measured p50 | Measured p95 |
|---|---:|---:|
| Decode + preprocess | 30ms | 68ms |
| OCR | 775ms | 1.070s |
| Extraction + rules | 16ms | 22ms |
| Pipeline end to end | 839ms | 1.117s |
| UI render | Not measured | Not measured |

Model load is excluded because it must happen **once at startup**, not per request.

## Two Streamlit rules that are easy to get wrong

1. **Cache the OCR engine with `@st.cache_resource`.** Streamlit reruns the entire script on every interaction. An uncached model load would repeat on every rerun and blow the budget by itself — this is the single most likely way to miss 5s.

2. **Run batches through a worker pool with visible progress.** Streamlit's rerun model is single-threaded by default. 300 sequential labels with no progress indicator is the exact failure mode that killed the vendor pilot: the work may finish, but the agent has already given up.

## Cold start on the deployment host

Streamlit Community Cloud's free tier (like the HuggingFace Spaces tier originally targeted) sleeps after inactivity, so weights must be present at **install** time, never fetched on first request. A cold-start download would blow the entire budget on the first label an evaluator tries — the only one that shapes their impression.

**Already satisfied, verified 2026-07-31:** `rapidocr-onnxruntime==1.4.4` ships its weights inside the wheel (3 ONNX files, 16.2 MB), so `pip install` handles this with no separate download step. The live risk is now the opposite one: do not switch to a non-default model that fetches at runtime, and do not add a lazy loader.

## First data point (not the benchmark)

On macOS arm64 / CPython 3.11.15, default RapidOCR config, one synthetic 600×120 single-line image: **model load 0.19s, inference 1.05s.**

Model load is comfortably cheap, which confirms the cached-singleton design is sufficient. The 1.05s figure is *not* encouraging — that was a trivial image, and a real 2000px label with a dozen text regions will be slower against a 1.5s budget. Treat OCR as the stage most likely to miss. `/bench-ocr` on real labels is what settles it.

## Measure, don't assert

No latency number in this repo is measured until `/bench-ocr` has run. Report p50 and p95, not the mean — an agent's experience of "sometimes it hangs" lives in the tail. If the budget is missed, re-derive it and write down the real figure rather than quietly shipping past it.
