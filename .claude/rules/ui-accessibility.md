---
paths:
  - "app.py"
---

# The Streamlit layer

## Zero verification logic here

If you are about to write a comparison, a threshold, a normalization step, or a unit conversion in `app.py`, **stop** — it belongs in `src/labelcheck/`. No exceptions for "it's just one line".

This is the rule that keeps the domain logic testable without invoking OCR, and lets the UI or the OCR engine be swapped independently. It erodes one convenience at a time.

`app.py` does four things: collect input, call `verify()`, render `LabelReport`, offer the export.

## Radical simplicity

Sarah's benchmark is literal: *"something my mother could figure out"* — she's 73 and learned to video call last year. Half the compliance team is over 50, and Dave still prints his emails.

- Large targets. Generous spacing. No dense control panels.
- **One obvious path.** Upload → results. Do not make the agent choose a mode, a profile, or an engine before they can start.
- No hidden menus, no accordions concealing the primary action, no hunting for buttons.
- No jargon. Not "OCR confidence", not "token_sort_ratio", not "threshold". Say what the agent would say: "we read this as", "close but worth checking".
- Errors in plain language with a next action. A bad photo says "this image is too blurry to read — try a straight-on shot in better light", not an exception.

## Rendering results

- **Always show the crop.** The bounding-box region a value was read from is the trust mechanism — it is how an agent decides in two seconds whether to believe the tool. A verdict without its evidence is just an assertion.
- **`REVIEW` must be visually distinct from `FAIL`**, not a lighter shade of it. They mean different things: one asks for judgment, the other reports a violation. Collapsing them visually re-creates the binary the three-state model exists to avoid.
- **Never render an unevaluated check as green.** `NOT_EVALUATED` and acknowledged heuristics get their own treatment and say so in words. See `.claude/rules/verdicts.md`.
- Never present a `FAIL` as a rejection. The tool flags; the agent decides.

## Why Streamlit

Retained deliberately. Its drag-and-drop upload and zero-learning-curve surface map directly onto the accessibility requirement, and the brief prefers a complete simple app over an incomplete sophisticated one. The cost is the rerun model, which the two rules in `.claude/rules/performance.md` exist to contain.
