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

| Stage | Budget (warm) |
|---|---|
| Decode + preprocess | ≤ 400ms |
| OCR | ≤ 1.5s |
| Extraction + rules | ≤ 100ms |
| UI render | remainder |

Model load is excluded because it must happen **once at startup**, not per request.

## Two Streamlit rules that are easy to get wrong

1. **Cache the OCR engine with `@st.cache_resource`.** Streamlit reruns the entire script on every interaction. An uncached model load would repeat on every rerun and blow the budget by itself — this is the single most likely way to miss 5s.

2. **Run batches through a worker pool with visible progress.** Streamlit's rerun model is single-threaded by default. 300 sequential labels with no progress indicator is the exact failure mode that killed the vendor pilot: the work may finish, but the agent has already given up.

## HuggingFace Spaces cold start

The free tier sleeps after inactivity. OCR model weights must be downloaded at **build** time — in the `Dockerfile` or an equivalent build step — never lazily on first request. A cold-start weight download would blow the entire budget on the first label an evaluator tries, which is the only one that shapes their impression.

## Measure, don't assert

No latency number in this repo is measured until `/bench-ocr` has run. Report p50 and p95, not the mean — an agent's experience of "sometimes it hangs" lives in the tail. If the budget is missed, re-derive it and write down the real figure rather than quietly shipping past it.
