# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project status

**Pre-code.** No application source exists yet. The module layout below is a specification, not a description — and the commands are forward-looking, so do not run them expecting them to work until the corresponding files exist.

- `README.md` is the **source of truth**. It is a TTB take-home brief: build an AI-powered alcohol label verification prototype that checks label artwork against the field values in a COLA application.
- `RESOURCES.md` is an **advisory** stack recommendation, not binding. It is superseded on the OCR engine only — see `docs/adr/0001-ocr-engine.md`.

<!-- Once src/ exists, the module tree below becomes derivable from the codebase and should be
     trimmed out of this file. It earns its place only while it is still the spec. -->

## Hard requirements

The brief buries its real constraints inside stakeholder interview prose. These are the non-negotiables, each traceable to a specific claim in `README.md`:

| Constraint | Source | Rule |
|---|---|---|
| **< 5 seconds per label, end to end** | Sarah Chen — the scanning-vendor pilot took 30-40s and agents abandoned it | Hard budget. Governs every stack and architecture choice. |
| **No dependency on outbound cloud APIs** | Marcus Williams — the federal firewall blocked the vendor's ML endpoints | The core verification path must run fully local/offline. |
| **Batch upload of 200-300 labels** | Sarah Chen / Janet, Seattle office | First-class feature, not an afterthought bolted onto single-label mode. |
| **Government warning matched exactly** | Jenny Park — she rejected a label for using title case | Normalized *exact* comparison, never fuzzy. Case check on `GOVERNMENT WARNING:`. |
| **Human judgment on brand names** | Dave Morrison — `STONE'S THROW` vs `Stone's Throw` is "obviously the same thing" | Normalize then fuzzy match. Ambiguity escalates to a human; never auto-fail a near match. |
| **Radical UI simplicity** | Sarah Chen — "something my mother could figure out", 73-year-old benchmark, half the team is over 50 | Large targets, one obvious path, no hidden menus, no jargon, no hunting for buttons. |
| **Tolerate imperfect photographs** | Jenny Park — weird angles, bad lighting, glare on the bottle | Preprocessing pipeline. Stretch goal; degrade gracefully rather than crash. |
| **Store nothing sensitive** | Marcus Williams — PII and document retention concerns | Process in memory. Do not persist uploaded images or extracted text to disk. |

Explicitly **out of scope**: integration with the COLA system (Marcus: "that's a whole different beast with its own authorization requirements"). This is a standalone proof of concept.

The brief also states the grading preference directly: *"A working core application with clean code is preferred over ambitious but incomplete features. Document any trade-offs or limitations."* When trading scope against polish, cut scope and write the limitation down in `docs/limitations.md`.

## Commands

> Forward-looking. None of these work until the corresponding files exist.

```bash
# Environment — ALREADY BUILT and verified (CPython 3.11.15, all imports resolve).
# Recreate only if .venv is missing. `python3.11` is not installed on this machine;
# uv supplies it. 3.11 has the broadest wheel coverage for onnxruntime/opencv.
uv venv --python 3.11
uv pip install -r requirements-dev.txt          # runtime deps + pytest/ruff
# NOTE: `uv venv` does not create .venv/bin/pip. Use `uv pip install` / `uv pip freeze`.
# requirements.txt alone is the runtime set — it is what HF Spaces installs.
# No-uv fallback: python3.13 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt

# Run the app locally
.venv/bin/streamlit run app.py

# Fast test suite (pure logic, no OCR)
.venv/bin/pytest -m "not slow"

# Full suite including end-to-end OCR integration tests
.venv/bin/pytest

# A single test
.venv/bin/pytest tests/test_warning.py::test_title_case_warning_fails -v

# Lint / format
.venv/bin/ruff check .
.venv/bin/ruff format .
```

Invoke venv interpreters by path as shown; do not rely on shell activation persisting between calls.

**Deployment** targets HuggingFace Spaces (free tier). Pushing to the Space's `main` triggers a rebuild. Model weights must be present at **build** time, never fetched on first request — the free tier sleeps after inactivity, and a cold-start download would blow the budget on the first label an evaluator tries. Verified: `rapidocr-onnxruntime==1.4.4` ships its weights inside the wheel (3 ONNX files, 16.2 MB), so `pip install` already satisfies this for the default config. The remaining risk is introducing a non-default model that *does* fetch at runtime — don't.

## Architecture

### The core contract

```python
verify(image_bytes: bytes, expected: ApplicationRecord) -> LabelReport
```

**The Streamlit layer contains zero verification logic.** This is the rule that matters most. It keeps the domain rules as pure functions that are deterministically testable without invoking OCR, and lets the UI or the OCR engine be swapped independently. If you find yourself writing a comparison, a threshold, or a normalization step inside `app.py`, it belongs in `src/labelcheck/` instead.

### Module layout

```
app.py                      # Streamlit entrypoint. Thin. Widgets and rendering only.
src/labelcheck/
  config.py                 # Thresholds, tolerances, statutory warning text. Single source of truth for constants.
  models.py                 # Dataclasses: TextBlock, FieldResult, LabelReport, ApplicationRecord, Status
  pipeline.py               # Orchestrator implementing verify()
  preprocess.py             # EXIF orientation, deskew, perspective correction, CLAHE, upscaling
  ocr.py                    # Engine wrapper. Cached singleton. Returns TextBlock[] with bounding boxes.
  extract.py                # TextBlock[] -> candidate field values
  normalize.py              # Casefold, punctuation stripping, unit and number normalization
  rules/                    # One module per field, each returning a FieldResult
    brand.py  class_type.py  alcohol.py  net_contents.py  warning.py  origin.py
  batch.py                  # Manifest parsing, worker-pool execution, progress reporting
  report.py                 # LabelReport[] -> pandas DataFrame -> CSV export
tests/
```

### Data flow

`upload → preprocess → OCR → extract candidates → per-field rules → LabelReport → render/export`

OCR must return **bounding boxes alongside text**, not bare strings. The boxes are load-bearing twice over: they let the UI show the agent the exact cropped region a value came from (the trust mechanism), and they are the only available signal for type-size heuristics.

## Where the rest of the guidance lives

Detailed rules live in `.claude/rules/`. Two of them load every session; the rest load only when a matching file is opened — **which will not happen while you are creating that file for the first time.** During the build pass, read the rule before writing the module:

| Before writing | Read |
|---|---|
| `src/labelcheck/rules/*`, `models.py` | `.claude/rules/verdicts.md` *(always loaded)* |
| `src/labelcheck/rules/warning.py`, the warning constant in `config.py` | `.claude/rules/government-warning.md` *(always loaded)* |
| `src/labelcheck/ocr.py`, `preprocess.py` | `.claude/rules/ocr-preprocess.md` |
| `src/labelcheck/pipeline.py`, `batch.py`, anything on the hot path | `.claude/rules/performance.md` |
| `src/labelcheck/batch.py`, `report.py` | `.claude/rules/batch-manifest.md` |
| `app.py` | `.claude/rules/ui-accessibility.md` |
| `tests/**` | `.claude/rules/testing.md` |

Procedures are skills, invoked by name:

| Skill | Use for |
|---|---|
| `/build` | **The goal command.** Executes the whole project in phases, each with a mechanical gate. Resume with `/build <phase>`. |
| `/verify-cfr-text` | Diff the statutory warning in `config.py` against the live 27 CFR 16.21. **Unresolved — run before shipping.** |
| `/bench-ocr` | Measure RapidOCR vs EasyOCR against the 5s budget. **Unresolved — the engine choice and every latency figure are currently unmeasured.** |
| `/add-field-rule` | Scaffold a new per-field rule with its normalization helpers and tests. |

Reference documents, read on demand: `docs/adr/0001-ocr-engine.md` (why RapidOCR, and the fallback trigger) and `docs/limitations.md` (the trade-offs the brief asks to be documented — keep it current as decisions land).
