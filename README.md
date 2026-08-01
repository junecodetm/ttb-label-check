---
title: Alcohol Label Verification
sdk: docker
app_port: 8501
---

# Alcohol label verification

Deployed URL: **TBD** (the orchestrator will add the HuggingFace Spaces URL after deployment)

This is an offline tool that checks alcohol label artwork against the field values in a COLA application and shows a compliance agent what matches, what does not, and what still needs human judgment.

## Setup and run

The project targets Python 3.11. Create the environment and install the application plus development tools with:

```bash
uv venv --python 3.11
uv pip install --python .venv/bin/python -r requirements-dev.txt
.venv/bin/streamlit run app.py
```

`uv venv` does not create `.venv/bin/pip`. Keep using `uv pip install`, with the environment's Python selected as shown above. For a runtime-only local install, use `requirements.txt` instead of `requirements-dev.txt`.

Run the checks with:

```bash
.venv/bin/pytest -q
.venv/bin/ruff check .
```

To build and run the same Docker image used by the HuggingFace Space:

```bash
docker build -t labelcheck .
docker run --rm -p 8501:8501 labelcheck
```

Open `http://localhost:8501`. The Space metadata at the top of this file selects the Docker SDK and routes port 8501.

## Approach

The pipeline is:

`upload → preprocess → OCR → extract → per-field rules → report`

The actionable verdict model has three states: `PASS`, `REVIEW`, and `FAIL`. A binary verdict was wrong for this work because OCR uncertainty and legitimate near matches, such as capitalization or punctuation differences in a brand name, still need an agent's judgment. `NOT_EVALUATED` is reserved for checks that did not actually run; it is not presented as a passing verdict. The tool flags evidence but never issues a final rejection.

Every field result carries a crop from the source artwork. The report puts that crop next to the application value, extracted value, and reason for the verdict. This is the trust mechanism: an agent can inspect the exact pixels behind a result instead of taking the OCR output on faith.

## Tools used

| Tool | Why it is used |
|---|---|
| Streamlit | Provides the single-label and batch user interface with little presentation-layer code. |
| RapidOCR on ONNX Runtime | Runs OCR locally on CPU. Its model weights ship in the wheel, so startup never downloads a model. |
| OpenCV | Decodes images, corrects orientation and perspective, improves contrast, and produces evidence crops. |
| RapidFuzz | Scores fields where a near match should go to human review instead of failing automatically. |
| pandas | Builds batch result tables and CSV exports. |

Everything runs locally and the verification path makes no outbound network calls. That is a hard requirement of the project, not a deployment preference.

## Assumptions and scope

- The image fixtures are synthetic rather than real photographed labels. They prove that the pipeline is wired correctly, not that it has real-world OCR accuracy.
- Batch mode uses a manifest CSV as the application-data channel. Its columns are `filename`, `brand_name`, `class_type`, `alcohol_content`, `net_contents`, `bottler`, and optional `origin_country`.
- Integration with the COLA system is explicitly out of scope. Single-label values come from the form; batch values come from the manifest.
- Uploaded images, extracted text, and crops stay in memory. Nothing is persisted to disk.

## Measured performance

The final warm benchmark covered 18 samples: three timed runs for each of six synthetic variants. End-to-end pipeline latency was **0.839 seconds p50** and **1.117 seconds p95**. A separate 20-run clean-fixture measurement was **0.803 seconds p50** and **0.961 seconds p95**.

These figures were measured locally on macOS arm64 with CPython 3.11.15. Model startup and browser rendering were excluded, so they are pipeline measurements rather than a cold-start, UI, production-hardware, or real-photograph SLA.

## Limitations

- Government-warning boldness and minimum type size are `NOT_EVALUATED` rather than guessed.
- The synthetic corpus does not establish accuracy on real labels, especially curved, low-resolution, or heavily stylized photographs.
- There is no COLA integration.
- Nothing is persisted, so there is no history, resumable batch, or audit trail.
- Image correction degrades gracefully when it cannot recover a poor photograph; the report does not pretend the unreadable evidence passed.

See [limitations and benchmark details](docs/limitations.md) for the measured accuracy results, accepted trade-offs, and remaining production work. The original take-home brief is preserved at [docs/brief.md](docs/brief.md).
