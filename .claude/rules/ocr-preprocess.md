---
paths:
  - "src/labelcheck/ocr.py"
  - "src/labelcheck/preprocess.py"
---

# OCR and image preprocessing

## Engine: RapidOCR, not EasyOCR

RapidOCR (PP-OCR models on ONNX Runtime) is the one substantive departure from `RESOURCES.md`. EasyOCR pulls in PyTorch at ~800MB installed against RapidOCR's ~15MB of ONNX models, which on the HuggingFace Spaces free tier is the difference between a workable cold start and a build timeout; ONNX Runtime CPU inference is also materially faster per image, which is where the margin for the 5s budget comes from. Both run fully offline, so Marcus's firewall constraint holds either way.

**This choice is reasoned, not benchmarked.** Full rationale and the fallback trigger: `docs/adr/0001-ocr-engine.md`. Run `/bench-ocr` before committing to it.

## The engine wrapper contract

- **Cached singleton.** The model loads once at process start, never per request. In Streamlit that means `@st.cache_resource` — see `.claude/rules/performance.md`.
- **Returns `TextBlock[]`, never bare strings.** Every block carries its text, its bounding box, and the engine's confidence.

The bounding boxes are load-bearing twice over: they let the UI show the agent the exact cropped region a value came from — which is the trust mechanism, not a nicety — and they are the only available signal for type-size heuristics. A wrapper that flattens OCR output to a string makes both impossible and forces a rewrite.

Keep the engine behind this wrapper so it can be swapped. Nothing outside `ocr.py` should import RapidOCR directly.

## Preprocessing is conditional, not unconditional

Jenny's requirement is tolerance for weird angles, bad lighting, and glare on the bottle. Degrade gracefully rather than crash — a photograph the pipeline cannot straighten should still be OCR'd as-is and reported honestly, never rejected with a stack trace.

Available steps, roughly in order:

1. EXIF orientation correction
2. Deskew
3. Perspective correction (`warpPerspective` on the largest quadrilateral contour)
4. CLAHE for glare and uneven lighting
5. Upscaling for low-resolution mobile uploads

**Gate them behind an image-quality check.** Preprocessing is not free, and running every step on a clean 2000px studio shot spends budget for nothing. Assess first (resolution, blur, skew angle, contrast), then apply only what the image needs.

Running OCR twice — once raw, once preprocessed — to compare confidence doubles the single most expensive stage. If you do it, do it **only** for images that fail the quality gate, never as the default path.

## In-memory only

Decode from bytes and keep intermediates in memory. Do not write uploaded images, crops, or preprocessed frames to disk, not even to a temp directory. Marcus's constraint is a hard requirement, and `tests/` enforces it statically.
