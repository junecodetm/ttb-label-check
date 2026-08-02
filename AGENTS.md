# AGENTS.md — instructions for Codex

## Read these before writing code

1. **`CLAUDE.md`** — the architecture, the `verify()` contract, the module layout, and the
   table of hard requirements. Read it first, in full.
2. **The rule that governs the file you are about to write.** `CLAUDE.md` has the mapping
   under *"Where the rest of the guidance lives"*. The rules in `.claude/rules/` are
   binding, not advisory. Read the rule **before** writing the module, not after.

`docs/brief.md` is the source-of-truth brief; `README.md` is the deliverable written
against it.

## Hard boundaries — do not cross

- **Never run `git commit`, `git add`, or any history-modifying git command.** Leave the
  working tree dirty; the orchestrator commits.
- **Never edit** `requirements.txt`, `requirements-dev.txt`, `.claude/**`, `docs/cfr/**`,
  or `AGENTS.md`.
- **Never add a dependency.** The pinned set in `requirements.txt` is what Streamlit
  Community Cloud installs and what the venv has. If you believe you need a new package, stop and
  say so in your summary instead of installing it.
- **Never introduce a model that downloads weights at runtime.** RapidOCR's weights ship
  inside the wheel; that property is load-bearing for the deployment target.

## Environment

```bash
.venv/bin/pytest -m "not slow"     # fast suite
.venv/bin/pytest                   # full suite, includes OCR
.venv/bin/ruff check .             # lint  (must be clean)
.venv/bin/ruff format .            # format
```

CPython 3.11.15. Invoke the venv interpreter **by path** as shown — do not rely on shell
activation persisting between commands. There is no `.venv/bin/pip`; use `uv pip` (but see
"never add a dependency" above).

## Definition of done for every task

- The stated gate command passes. Run it yourself; do not report done without running it.
- `.venv/bin/ruff check .` is clean.
- No dead code, no unused imports, no commented-out blocks, no `TODO` left as a placeholder
  for work you were asked to do.
- No scripts or scratch files at the repo root. Helper scripts go in `tools/`, test helpers
  in `tests/`.
- No generated images, CSVs, logs, or caches added to version control.
- Type hints on public functions. Docstrings that say *why*, not *what*.

## Recurring correctness traps in this codebase

These are the mistakes that matter most here. Each traces to a rule file:

- **Never report `PASS` for a check that did not actually run.** Use `NOT_EVALUATED`.
  A green unevaluated check is worse than an absent one.
- **The government warning is a normalized *exact* comparison. Never fuzzy, never
  casefolded, not even at a high threshold.** Case is the check.
- **Every `FieldResult` carries all five members**, including a non-empty `crop`. A result
  without its crop is not renderable — the crop is the trust mechanism.
- **Zero verification logic in `app.py`.** No comparison, threshold, normalization, or unit
  conversion there, not even a one-liner. It goes in `src/labelcheck/`.
- **Thresholds and tolerances live in `config.py`**, never inline in a rule module.
- **Normalization lives in `normalize.py`**, never inside `rules/`. Rule modules compare;
  they do not transform.
- **Nothing touches disk.** No image, crop, preprocessed frame, or extracted text is ever
  written to disk — not even to a temp dir. Process in memory. A static test enforces this.

## Reporting back

End your run with a summary of **at most 10 lines**:

```
FILES: <paths written or modified>
GATE:  <the exact command you ran>
RESULT: <pass/fail + the one decisive line of output>
NOTES: <anything the orchestrator must decide, or blank>
```

Do not paste diffs, full test output, or file contents into the summary. If you hit
something ambiguous that the rules do not settle, state it in `NOTES` and pick the option
most consistent with the rules — do not silently invent a requirement.
