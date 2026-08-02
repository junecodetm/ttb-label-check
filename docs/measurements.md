# Measurements

Every number in this repository should be reproducible by running a command in this
file. Where a figure has moved, both values are kept rather than the flattering one.

## How to reproduce

```bash
.venv/bin/python tools/bench_ocr.py            # per-stage latency and field accuracy
.venv/bin/python tools/bench_batch.py --count 300   # peak-season batch, wall time and RSS
.venv/bin/python tools/check_label.py IMAGE --brand ... # one real label, every verdict
```

## Single label latency

The requirement is Sarah Chen's: results in about five seconds, or agents stop using
the tool. It is met with room to spare, but the exact figure depends heavily on what
else the machine is doing, so the conditions matter more than the number.

| Measurement | p50 | p95 | Conditions |
|---|---:|---:|---|
| Deployed app, observed in a browser | **0.9s** | not sampled | Streamlit Community Cloud, clean sample label, wall clock as the agent sees it |
| `tools/bench_ocr.py`, 18 samples over 6 variants | **1.084s** | **1.511s** | macOS arm64, CPython 3.11.15, quiet-ish machine |
| Same, with a browser and background agents running | 1.312s | 2.295s | same box, load average ~12 on 10 cores |
| Earlier figure published in this repo | 0.839s | 1.117s | same tool, less loaded machine, before the changes below |

The 0.839s p50 previously quoted here did not reproduce on re-measurement. It was not
wrong when taken; it was taken on an idle machine. The honest summary is that a single
label costs roughly **one to one and a half seconds warm**, against a five second
budget, and the tail grows with machine load rather than with label difficulty.

Warm stage split, from the same 18-sample run:

| Stage | p50 | p95 |
|---|---:|---:|
| Decode + preprocess | 0.034s | 0.068s |
| OCR | 1.032s | 1.443s |
| Extraction + rules | 0.019s | 0.025s |

OCR is ~95% of the budget. Model load is excluded because it happens once at startup;
the weights ship inside the `rapidocr-onnxruntime` wheel, so nothing is fetched at
first request.

**Re-measured 2026-08-01** after adding the standards-of-fill check:
end to end p50 **1.159s** / p95 **1.526s** on the same tool and machine under ordinary
load; extraction + rules moved from 0.019s to **0.020s** p50 (~4 ms for the new check,
noise-level). Field accuracy per variant is unchanged. The live deployed app measured the
same day answers the sample label in **0.9s** and a 4-label batch in **3.5s** end to end.

## Field accuracy on synthetic variants

Six fields per label, three timed runs each, so 18 field reads per variant.

| Variant | Correct | Failing fields |
|---|---:|---|
| Clean | 18/18 | — |
| Ornate / script | 18/18 | — |
| Rotated 5° | 18/18 | — |
| Glare | 18/18 | — |
| Low resolution | 9/18 | alcohol punctuation, merged bottler words, warning spacing |
| Combined adversarial | 12/18 | alcohol punctuation, warning spacing |

These are **synthetic** fixtures rendered by `tests/fixture_factory.py`. They establish
that the pipeline degrades rather than crashes; they do not establish accuracy on real
photographs. See the real-label section below, which is the honest one.

## Batch at peak season

300 labels, six variants cycled, `tools/bench_batch.py --count 300`:

| | |
|---|---|
| Wall time | **346.2s** (5 min 46s) |
| Per label | 1.154s |
| Throughput | 0.87 labels/second |
| Peak RSS | **1110MB** (679MB before the batch began) |
| Errors | 0 |
| Verdicts | 250 PASS, 50 FAIL |

The 50 FAILs are the low-resolution variant, one sixth of the run, consistent with the
9/18 above. Peak memory fits a ~2.7GB single-instance host with room left, so the batch
path needs no chunking. Note the corpus is 40MB of synthetic PNGs; 300 real
photographs at 1-3MB each would add roughly a gigabyte of raw bytes and would need
re-measuring before being promised.

### Why there is no OCR engine pool

The OCR engine is a process-wide singleton behind a lock, so batch workers serialize on
the expensive stage. That looks like the obvious thing to fix. Measured, it is not:

| Engines × intra-op threads | Seconds per label |
|---|---:|
| 1 × 6 (shipped) | 1.228 |
| 2 × 3 | 1.048 |
| 3 × 2 | **1.002** |
| 4 × 1 | 1.093 |
| 4 × 2 | 1.080 |
| 6 × 1 | 1.303 |

24 labels, one process, same load. ONNX Runtime's intra-op threads already saturate the
CPU, so more engines mostly contend — six engines are worse than one. The best case is
1.23x for about +265MB of duplicated weights, on a host where memory is the binding
constraint and cores are few. The pool was therefore not built, and the effort went to
progress reporting, an estimated time remaining, and cancellation instead.

## Real TTB label artwork

Taken from the TTB Public COLA Registry, the only source pairing genuine approved
artwork with structured ground truth. This is where the synthetic corpus turned out to
be flattering.

**How to reproduce it.** There is deliberately no automated fetcher in this repo. The
registry sits behind an F5/TSPD JavaScript bot challenge: a plain HTTP client receives
the challenge page instead of the record, and defeating that on a government site is not
something this project will do. The manual procedure, which is what produced the results
below, takes about a minute per label:

1. Search the registry at `https://ttbonline.gov/colasonline/publicSearchColasBasic.do`
   in a real browser and open a result. The detail page carries the ground truth —
   brand name, class/type code, origin code, and the bottler's name and address.
2. Follow **Printable Version** to
   `viewColaDetails.do?action=publicFormDisplay&ttbid=<TTB_ID>` and read the label
   image's `<img src>`, which has the form
   `publicViewAttachment.do?filename=<NAME>&filetype=l`.
3. Save the image, then check it with
   `.venv/bin/python tools/check_label.py IMAGE --brand ... --class-type ...`.

An earlier Open Food Facts fetcher was written and discarded: its US alcohol categories
return beef jerky, olive oil and vitamin water, and it holds almost no back-label
photographs, which is where the government warning lives.

Test case: TTB ID 25079001000562, a Canadian blended whiskey. OCR read the stylised
label **without inter-word spaces** — `GOVERNMENTWARNING:`, `IMPORTED&BOTTLEDBYSAHALEE`,
`Alcohol Content40% by Vol` — and every extraction signal assumed spaces.

| Field | Before | After |
|---|---|---|
| Alcohol content | NOT_EVALUATED | **PASS** |
| Government warning prefix | not located | **REVIEW** (correct prefix, spacing unresolved) |
| Bottler | NOT_EVALUATED | FOUND, reported FAIL with evidence |
| Brand | FAIL on decorative text | REVIEW |

The fixes are in `config.py` (alcohol markers), `extract.py` (space-tolerant signals)
and `rules/warning.py` (space-insensitive exact second pass). What remains is recorded
in `docs/limitations.md` — chiefly that COLA images are composite artwork sheets whose
side-by-side panels defeat horizontal line grouping, and that a full-width OCR
substitution such as `）` for `)` still fails the warning comparison by design.
