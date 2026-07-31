---
description: Execute the entire TTB label verification build, phase by phase, from empty repo to deployable app.
argument-hint: [phase-number-to-resume-from]
disable-model-invocation: true
---

# Build the label verification app

The goal command. Runs the whole project end to end. Resume from a phase with `/build 4`.

Requirements, the `verify()` contract, and the module layout are in `CLAUDE.md`. Domain rules are in `.claude/rules/` — **read the rule before writing the module it governs**, per the map in `CLAUDE.md`. The path-scoped rules will not auto-load while you are creating a file for the first time. Do not restate those rules here; follow them.

## What "done" means

The brief's deliverables:

1. Source repository with all source code
2. `README.md` with setup and run instructions
3. Documentation of approach, tools used, assumptions made
4. A deployed, working application URL

Plus the grading preference, which is the tiebreaker on every judgment call: *"A working core application with clean code is preferred over ambitious but incomplete features. Document any trade-offs or limitations."*

## Phases

Each phase has a **gate** — a mechanical check, not a judgment. Do not start a phase until the previous gate is green. If a gate fails, fix it before proceeding; a phase built on a red gate costs more to unwind than to redo.

### Phase 0 — Environment

Create the venv with the commands in `CLAUDE.md` and install `requirements-dev.txt`.

`python3.11` is **not** installed on this machine. Use `uv venv --python 3.11`, which is installed and downloads 3.11 on first use. 3.11 is chosen for wheel coverage: onnxruntime and opencv wheels are least likely to exist for 3.13/3.14, and a source build of opencv will cost the session.

Confirm every import resolves. If `rapidocr-onnxruntime` does not resolve, try `rapidocr` plus `onnxruntime` and record which worked in `requirements.txt`. Then pin exact versions with `.venv/bin/pip freeze` — HF Spaces needs reproducible pins, and the Dockerfile should pin the same Python version as the venv.

> **Gate:** `.venv/bin/python -c "import cv2, rapidfuzz, pandas, streamlit, numpy, PIL"` exits 0, the OCR engine imports, and `requirements.txt` carries pinned versions.

### Phase 1 — Discharge the CFR risk first

Run `/verify-cfr-text`. Do this **before** writing `rules/warning.py`, not after. Every warning test you write asserts against that constant; if it is wrong, the tests confirm the wrong thing and look green while doing it.

> **Gate:** the statutory text in `config.py` is confirmed against the live CFR, with source URL and retrieval date recorded beside it.

### Phase 2 — Pure core

`models.py` (`TextBlock`, `FieldResult`, `LabelReport`, `ApplicationRecord`, `Status`), `config.py` (thresholds, tolerances, statutory text), `normalize.py`. No OCR, no images, no Streamlit. `Status` must include `NOT_EVALUATED` — see `.claude/rules/verdicts.md`.

Write tests for `normalize.py` as you go. It is pure string and number work and there is no cheaper place to be exhaustive.

> **Gate:** `.venv/bin/pytest -m "not slow"` passes and `.venv/bin/ruff check .` is clean.

### Phase 3 — The rules, and the acceptance cases

One module per field under `rules/`, each returning a `FieldResult`. Use `/add-field-rule` for the shape.

Write the six stakeholder acceptance cases from `.claude/rules/testing.md` **first**, then make them pass. They are the acceptance criteria in disguise; deriving thresholds to fit them is the correct direction of causation.

This phase is where correctness is actually decided. It is also the cheapest phase to test. Spend disproportionate effort here.

> **Gate:** all six acceptance cases green, every fuzzy-matched field has a `REVIEW`-band test, and the static no-disk-persistence test from `.claude/rules/testing.md` exists and passes.

### Phase 4 — Perception

`preprocess.py`, `ocr.py`, `extract.py`, `pipeline.py`. This is where `verify()` becomes real.

If no label fixture is available, generate one: render the sample label fields from the brief onto an image with PIL. A synthetic fixture keeps the slow suite runnable and is far better than an untested pipeline. Add photographed and stylized fixtures when you can get them.

> **Gate:** `verify()` on a fixture returns a `LabelReport` with a `FieldResult` per field, each carrying a non-empty crop. No field returns `PASS` without having been evaluated.

### Phase 5 — Single-label UI

`app.py`. Upload → typed expected values → results with crops. **A working vertical slice.** Stop and confirm it actually works before adding batch.

Time it warm, with the model cached. This is the first honest read on the 5-second requirement.

> **Gate:** the app runs; one label goes end to end; the warm timing is recorded (whatever it is — record the real number, including if it misses).

### Phase 6 — Batch

`batch.py`, `report.py`, and the batch surface in `app.py`. Manifest schema and reconciliation rules are in `.claude/rules/batch-manifest.md`.

> **Gate:** a batch of ≥20 images including one manifest row with no image **and** one image with no manifest row completes, reports both as errors rather than dropping them, sorts FAIL → REVIEW → PASS, and exports CSV.

### Phase 7 — Measure, document, ship

- Run `/bench-ocr`. If RapidOCR loses on stylized typography, swap to EasyOCR — `ocr.py` is the only file that changes — and re-derive the budget from measurement.
- Write the `Dockerfile`. **OCR weights download at build time, never on first request.** This is the single most likely deployment failure.
- Update `docs/limitations.md`: close every OPEN entry with its measured result. Do not close one by deleting it.
- Update `docs/adr/0001-ocr-engine.md` status from *Proposed*.
- The deliverable `README.md`: the current `README.md` is the brief and is `CLAUDE.md`'s stated source of truth. **Copy it to `docs/brief.md` first**, then write the deliverable README (setup, run, approach, tools, assumptions, limitations), then update the `CLAUDE.md` pointer to `docs/brief.md`. In that order — do not overwrite the brief before it is preserved.

> **Gate:** all four deliverables exist, `docs/limitations.md` has no OPEN entry left unaddressed, and the full suite passes.

## If time runs short

Cut in this order, and write down each cut in `docs/limitations.md`:

1. Bold-detection heuristic → `NOT_EVALUATED` (already an accepted trade-off)
2. Type-size heuristic → `NOT_EVALUATED`
3. Perspective correction and the quality gate → straight OCR, degraded on bad photos
4. Country of origin → the least common field

Never cut: the three-state verdict model, the exact warning comparison, crops attached to results, or batch mode. Those are the hard requirements — a build missing any of them has failed the brief regardless of polish.

## Reporting

At each gate, state the real result. A missed latency budget, a fixture you could not source, a check you stubbed — say so plainly and record it. The brief asks for limitations to be documented; an accurate limitations file is a graded deliverable, not an admission.
