---
paths:
  - "src/labelcheck/batch.py"
  - "src/labelcheck/report.py"
  - "app.py"
---

# Batch mode and the manifest contract

Batch is a first-class feature, not an afterthought bolted onto single-label mode. Sarah: peak season brings importers who *"dump 200, 300 label applications on us at once"*, and Janet in the Seattle office has been asking for years.

## Batch needs an application-data channel

Verification is always a comparison of the label against **what the application says**. A pile of images alone is not verifiable — there is nothing to compare against. This is easy to overlook and painful to retrofit.

- **Single-label mode**: the agent types the expected field values into the form.
- **Batch mode**: the agent uploads images **plus a CSV manifest** pairing each image filename to its expected values.

## Manifest schema

```
filename, brand_name, class_type, alcohol_content, net_contents, bottler, origin_country
```

`origin_country` is blank for domestic products; a blank value means the country-of-origin rule does not apply, not that it failed. Header row required. Match `filename` against uploaded images case-insensitively — agents will not get the casing right on 300 rows.

## Reconciliation errors are results, not silence

Two failure modes, both reported as rows in the output rather than skipped:

- A manifest row whose image was not uploaded.
- An uploaded image with no matching manifest row.

Silently dropping either is the worst possible behaviour at 300 labels: the agent sees 287 results, believes the job is done, and never learns which 13 vanished.

## Output

Results render as a sortable table ordered by severity — **FAIL, then REVIEW, then PASS** — so an agent triaging 300 labels sees the problems first. Reconciliation errors sort with the failures.

One-click CSV export via pandas. The export carries the same columns the table shows, including the extracted values and confidence, so the agent can work the queue outside the tool.

## Progress is mandatory

See `.claude/rules/performance.md` — a worker pool with a visible progress indicator, not a sequential loop behind a spinner. The vendor pilot did not fail because the work was impossible; it failed because agents could not tell whether it was progressing.
