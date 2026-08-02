# Stack inventory (final-pass Phase 0)

Scratch inventory for the final audit pass. Verified against the working tree on 2026-08-01.

| Aspect | Finding |
|---|---|
| Frontend framework | Streamlit 1.60.0 (`app.py` — widgets and rendering only; zero verification logic) |
| Backend / API framework | None (Streamlit is the whole app; domain logic is the pure-Python package `src/labelcheck/`) |
| Runtime(s) & versions | CPython 3.11.15 in `.venv` (created with uv); pins in `requirements.txt` (streamlit 1.60.0, rapidocr-onnxruntime 1.4.4, opencv-python-headless 5.0.0.93, rapidfuzz 3.14.5, pandas 3.0.5, numpy 2.4.6, pillow 12.3.0, pillow-heif 1.5.0) |
| AI/OCR engine + local-or-remote | RapidOCR (ONNX runtime), **fully local** — weights ship inside the wheel (3 ONNX files, 16.2 MB), no outbound network calls anywhere in the package (verified by grep and by `tests/` offline guard). Engine choice recorded in `docs/adr/0001-ocr-engine.md` |
| Fuzzy-match / text-compare approach | RapidFuzz `token_sort_ratio` after normalization for brand/class (PASS ≥ 90 / REVIEW 70–90 / FAIL < 70); normalized **exact** comparison for the government warning (never fuzzy); numeric comparison with CFR tolerances for ABV and net contents |
| Deployment target + serverless? | Streamlit Community Cloud (long-running container, redeploys on push to `main`); `Dockerfile` kept verified for any container host. Not serverless |
| Live URL | https://ttb-label-check.streamlit.app |
| Test framework present? | pytest — 19 files, ~205 tests; `slow` marker separates OCR integration tests from the pure-logic fast suite |
| Lint/format present? | Ruff (check + format), configured in `pyproject.toml` (line-length 100, py311, E/F/I/UP/B) |
| Secrets committed? (Y/N) | **N** — no API keys exist at all (fully offline app); repo-wide grep for key patterns is clean |

## Single-label verify path (request → response)

1. `app.py:main` → `_handle_single_submission` (app.py:591) reads the upload bytes and the expected fields from the form.
2. `labelcheck.pipeline.verify(image_bytes, expected: ApplicationRecord) -> LabelReport` (pipeline.py:54) — the core contract:
   - `preprocess.py` — EXIF auto-orient, decode guards (80 MP cap), downscale to ≤ 1400 px long edge / upscale to ≥ 736 px short edge (quality-gated).
   - `ocr.py` — cached RapidOCR singleton (process-level lock + `@st.cache_resource` in app.py:137), returns `TextBlock[]` with bounding boxes.
   - `extract.py` — TextBlocks → per-field candidate values (+ crops).
   - `rules/` — one module per field, each returning a `FieldResult(status, expected, extracted, confidence, crop, detail)`; statuses PASS / REVIEW / FAIL / NOT_EVALUATED.
   - `LabelReport` rolls up overall status (FAIL > REVIEW > PASS > NOT_EVALUATED) and lists checks that could not run.
3. `app.py:_render_report` (app.py:242) renders per-field verdicts with the cropped image region each value was read from, plus CSV download.

## Batch path (200–300 labels)

1. `app.py:_render_batch_page` (app.py:273) → `_handle_batch_submission` (app.py:368): collects uploaded images + a CSV manifest.
2. `labelcheck.batch.parse_manifest` (batch.py:145) — encoding-fallback CSV parsing, per-row validation, duplicate detection.
3. `labelcheck.batch.run_batch` (batch.py:226) — bounded `ThreadPoolExecutor` (≤ 8 workers), per-item `progress_callback` + `result_callback` (partial results survive cancellation), manifest↔image reconciliation in both directions.
4. `labelcheck.report.results_to_dataframe` → `dataframe_to_csv` (report.py:59–69) → download button (app.py:463).
