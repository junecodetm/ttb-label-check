---
description: Verify the statutory government warning in src/labelcheck/config.py character-for-character against the live text of 27 CFR 16.21. Use before shipping, when writing the warning rule, or when warning comparisons behave unexpectedly.
allowed-tools: Read, Edit, WebFetch
---

# Verify the statutory warning text against the CFR

The warning constant in `config.py` was reproduced from memory. It is the single most consequential string in the project: if one word is wrong, every compliant label fails or a non-compliant one passes, and there is no visible symptom either way. This procedure discharges that risk.

> The offline requirement governs the **runtime application**, not this check. Fetching the CFR is a development-time action on a public source and does not put a network call on the verification path.

## Steps

1. **Read the current constant.** Open `src/labelcheck/config.py` and locate the government warning string. If the file does not exist yet, the reference text in `.claude/rules/government-warning.md` is the thing being verified instead.

2. **Fetch the authoritative text.** Retrieve 27 CFR 16.21 from eCFR:
   `https://www.ecfr.gov/current/title-27/chapter-I/subchapter-A/part-16/subpart-B/section-16.21`
   If that URL 404s or redirects, find the current location rather than falling back to a secondary source — a blog or a vendor page reproducing the text carries exactly the error this procedure exists to catch.

3. **Extract only the statutory sentence.** The regulation wraps the warning in surrounding prose about placement and legibility. What belongs in `config.py` is the text a label must bear, beginning `GOVERNMENT WARNING:` and ending `...may cause health problems.`

4. **Normalize only line-wrapping.** Collapse the source's line breaks to single spaces before comparing. Do **not** normalize case, punctuation, or spacing inside sentences — those are precisely what is being verified.

5. **Diff word by word.** Report every difference explicitly: word substitutions, missing or added words, punctuation changes, and any case difference. Pay particular attention to `(1)` / `(2)` numbering, the comma placement in the second sentence, and whether the word is `impairs` or `may impair`.

6. **Show the diff before changing anything.** Do not silently correct `config.py`. Print what differs, then apply the fix.

7. **Record provenance.** Add a comment above the constant with the source URL and the date retrieved, so the next person knows when it was last checked rather than re-doing this from scratch.

## Report

State plainly whether the constant matched. If it did, say so — a confirmed-correct result is the point of running this. If it did not, name each deviation and note that any existing test asserting on warning text needs re-checking, since it may have been passing against the wrong string.
