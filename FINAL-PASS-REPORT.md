# Final-pass report

Exhaustive audit-and-optimization pass over the TTB label-verification prototype,
executed 2026-08-01 on the `final-pass` branch. Each phase of the audit checklist was
run against the already-built application; this report records what was found, what was
changed, and what was deliberately left alone.

## 1. Summary verdict: **GO**

The working core was already sound; the one genuine feature gap the audit found — no
standards-of-fill check — is now implemented, eCFR-verified, and provenance-pinned. The
live deployment passed all three smoke tests during the audit at 0.9s per label.

## 2. Requirement matrix — before vs after

| # | Requirement | Before | After | Evidence |
|---|---|---|---|---|
| R1 | < 5s per label | Met | Met (re-verified) | Live 0.9s; local p50 1.159s / p95 1.526s post-change (`docs/measurements.md`) |
| R2 | 200–300 batch + progress | Met | Met (re-verified live) | 300 in 5m46s; live 4-label batch 3.5s with progress and CSVs |
| R3 | Ease of use, over-50 team | Met | **Improved** | Two-click demo verified live; added a visible keyboard focus ring (the crop fullscreen buttons had none) |
| R4 | Exact warning + all-caps check | Met | Met (confirmed) | Title-case fixture flagged live with word-level diff; byte-for-byte provenance test |
| R5 | Fuzzy brand judgment | Met | Met (confirmed) | `STONE'S THROW` acceptance test; PASS/REVIEW/FAIL bands |
| R6 | Firewall/offline | Met | Met (confirmed) | Zero outbound calls; weights ship in the wheel |
| R7 | Imperfect images | Met (stretch) | Met (confirmed) | Deskew/perspective/CLAHE; angled-and-glared sample reads clean |
| R8 | No storage + security note | Met (code) / gap (docs) | **Met** | Static no-persistence test; README now has the security & FedRAMP section |
| R9 | README complete | Partial | **Met** | Added requirements table, Mermaid diagram, screenshot, security section, hibernation note; quick start re-verified on a fresh clone |
| R10 | Live URL works | Met | Met (re-verified) | Three live smoke tests passed during the audit |
| R11 | Mandatory-field checks, current regs | **Partial** | **Met** | New: net contents checked against 27 CFR 5.203 / 4.72 authorized sizes incl. T.D. TTB-200 expansions; wine even-liter ≥4L rule; malt exempt per Part 7; 16.22 type-size tiers surfaced; wine <7% ABV FDA advisory |
| R12 | Error/empty states | Met | Met + upload cap | 25MB `maxUploadSize` added; the 200MB default could exhaust the host's 2.7GB RAM |
| R13 | Per-field confidence | Met | Met (confirmed) | FieldResult carries status/confidence/crop per field |
| R14 | Craft signals | Met | **Improved** | CI added; regulatory constants now provenance-pinned like the warning text |

## 3. Changes made, by phase

**Housekeeping** — committed the pending `RESOURCES.md` removal and fixed the three
dangling references (CLAUDE.md, AGENTS.md, ADR-0001 header). Rationale: dangling links
in an evaluator-facing repo read as rot.

**Phase 0** — `STACK.md`: stack table plus the exact single-label and batch
request→response traces.

**Phase 1** — verified `THT-INSTRUCTIONS.md` and `docs/brief.md` are content-identical;
confirmed `docs/requirements-audit.md` covers the requirement set; added the missing
error-handling and confidence-reporting rows plus the new container-size row.

**Phase 2 (the substantive change)** — standards-of-fill check:
- Verified both authorized-size lists against the live eCFR versioner API (title-27
  issue 2026-07-30) before hard-coding anything; the API XML is transcribed into
  `docs/cfr/27-cfr-5-203.txt` and `27-cfr-4-72.txt` and was diffed mechanically against
  the source. The CFR's own inconsistent T.D. TTB-200 dates (Jan. 10 vs Jan. 20) are
  reproduced verbatim and annotated.
- `verify_standard_of_fill` in `rules/net_contents.py`: metric readings compare exactly
  (701 mL can never pass); fl-oz readings get half a print step (~1.48 mL) so
  `25.4 fl oz` resolves to 750 mL; a nonstandard reading whose application value *is*
  authorized lands on REVIEW as a probable OCR misread; malt is NOT_EVALUATED because
  Part 7 has no standards of fill — the honesty invariant (“never PASS a check that did
  not run”) is preserved.
- Reference metadata surfaced honestly: the 16.22(b) type-size tiers now appear in the
  type-size check's NOT_EVALUATED detail (the check still never passes), and wine below
  7% ABV gets an FDA-jurisdiction advisory (27 CFR 4.10) without a status change. Both
  values are anchored (`27-cfr-16-22.txt`, `27-cfr-4-10.txt`) and provenance-pinned.
- Independent fresh-context review of the diff returned ACCEPT-WITH-NITS; every finding
  was addressed (jargon removed from user-visible PASS details, dead parameter dropped,
  misleading ambiguous-branch label fixed, absurd 10^100 fixture replaced, missing
  anchors added). The one declined recommendation — splitting into three commits — is
  declined because no file partition kept intermediate commits green.

**Phase 3** — re-benchmarked: the new check costs ~4 ms (rules stage 0.020s p50);
end-to-end p50 1.159s / p95 1.526s, recorded in `docs/measurements.md`. No new timing
code: the offline bench plus the in-UI elapsed time already answer the question.

**Phase 4** — manual keyboard/snapshot audit. One real defect found and fixed: no
visible focus ring on Streamlit's small icon buttons; added a 3px `:focus-visible`
outline for every control. Automated Lighthouse/axe scoring was not run — Streamlit
generates the DOM, so a score would grade the framework; the manual pass targeted what
the app actually controls.

**Phase 5** — 25MB upload cap (`maxUploadSize`; verified the dropzone hint updates);
GitHub Actions CI (ruff + format + fast suite via uv — the fast suite still needs full
deps because `pipeline` imports rapidocr/cv2 at collection time); `.env` gitignore
backstop; fixed the stale “HuggingFace Spaces” comment in `requirements.txt`.
`.env.example` deliberately omitted: the app has zero keys, so it would be an empty file.

**Phase 6** — README: inline requirements→features table, Mermaid pipeline diagram,
sourced-constants paragraph, security & production-hardening section (including the
FedRAMP boundary point), Community Cloud hibernation trade-off, result-view screenshot.
Quick start re-verified on a fresh clone (423 fast tests green from a cold environment).

**Phase 7** — live verification: sample demo 0.9s PASS; title-case fixture flagged with
the word-level diff `replace expected [GOVERNMENT WARNING] with extracted [Government
Warning]`; 4-label batch with progress in 3.5s. Console errors are Streamlit platform
noise (`/api/v2/user/details` 404 for anonymous viewers), not app defects.

## 4. Measured metrics

| Metric | Value |
|---|---|
| Live single label (warm) | **0.9s** (measured during audit) |
| Live 4-label batch | **3.5s** end to end |
| Local single label, post-change | p50 **1.159s** / p95 **1.526s** (loaded machine) |
| Rules-stage cost of the new check | ~4 ms |
| 300-label batch (prior measurement, unchanged path) | 346s, peak RSS 1110MB, 0 errors |
| Test suite | **426 passed** (423 fast + 3 slow), ruff + format clean |
| Accessibility | Manual keyboard pass; focus ring fixed; no automated score (see Phase 4) |

## 5. Known limitations and explicit cuts

All recorded in `docs/limitations.md`; headlines: warning boldness and physical type
size stay `NOT_EVALUATED` (never green); per-beverage mandatory-field sets and the
sulfite declaration are cut (the application record has no sulfite data); real-label
accuracy is established for a handful of COLA labels, not a corpus; composite COLA
artwork sheets are out of contract; Community Cloud sleeps after ~12h and needs a
manual wake click — documented, not papered over. Demo GIF cut in favor of a
screenshot. `COMPLETE.md` (the audit checklist itself) is deliberately left untracked.

## 6. “With more time” backlog (priority order)

1. Photographed-label accuracy corpus — the one claim the synthetic fixtures cannot make.
2. Column segmentation for composite COLA artwork sheets.
3. Stroke-width boldness heuristic for the warning prefix (reported as a labelled
   heuristic, never PASS).
4. Per-beverage mandatory-field sets once the application record carries the needed data.
5. An always-warm deployment (the Dockerfile is ready) if the 5s guarantee must cover
   the first request of the day.

## 7. Commits on `final-pass`

| Commit | Subject |
|---|---|
| 15b9671 | chore: remove advisory RESOURCES.md and fix dangling references |
| 0b67f5c | docs: add STACK.md inventory (final-pass phase 0) |
| 277ad2c | feat: check net contents against the 27 CFR standards of fill |
| 9e42beb | chore: re-measure after the fill check and add a visible keyboard focus ring |
| a85ec7a | chore: cap uploads at 25MB, add CI, backstop .env, fix a stale deploy comment |
| acc8511 | docs: README final pass — requirements table, architecture diagram, security note |
| (this) | docs: add the final-pass report |

## Go / no-go checklist

- [x] R1 warm latency < 5s (0.9s live / 1.526s p95 local)
- [x] R2 batch works with progress UI (live-verified; 300 measured)
- [x] R3 ease-of-use bar + AA basics (focus ring fixed; targets 52px; icon+text verdicts)
- [x] R4 warning verbatim + all-caps detection, tested (provenance-pinned)
- [x] R5 fuzzy brand match with confidence, tested
- [x] R6 offline constraint satisfied (zero outbound calls)
- [x] R7 imperfect-image handling present and scoped honestly
- [x] R8 nothing stored; security + FedRAMP note in README
- [x] R9 README complete
- [x] R10 live URL works (three smoke tests)
- [x] R11 per-beverage checks correct and current (T.D. TTB-200, eCFR-verified)
- [x] R12 error/empty/oversized states handled (25MB cap added)
- [x] Lint clean, 426 tests pass, CI configured, no secrets committed

> Note for review: merging this branch will redeploy the live app (Streamlit Community
> Cloud tracks `main`). All changes were verified locally and the suite is green, so
> that is expected to be safe — but it is a deploy, and this report can be dropped from
> the repo at merge if an audit artifact is unwanted in `main`.
