# M6 plan: report, repository, demo, deck and viva

SPEC C13: **M6 (weeks 12-13)**: technical report, GitHub repo, live demo, business deck (PPT), viva. **Definition of done:** the demo is rehearsed; every member can explain every stage.

**Team for M6:** only **P3 Udita (@udita-0707)** and **P4 Aman (@AmanKumar1411)** build, commit and review; each reviews the other's pull requests. The viva still involves all four members. P1 Kalash and P2 Dally therefore read every crib sheet and must be able to explain their own earlier stages (M2 data, M3 baseline and experiments).

M6 builds no new models. It turns what M1-M5 measured into documents people read, and makes sure every number in them traces back to a logged run or a saved report.

## Before M6 starts

1. **M4 closed:** the model is frozen, error categories are labelled, and `reports/m4/test_results.md` is on `main` (Step 0 of `docs/M5_PLAN.md`).
2. **M5 merged and tagged `m5`:** Aman has deployed. `reports/m5/deployment.md` has the public URL, and `reports/m5/load_test.md` has the public-URL rows, not TODO.
3. **Transformer:** decide whether the GPU DistilBERT run happens before the report. If not, the report says plainly that the M3 criterion "at least one transformer beats the baseline on val" was not met, and why.
4. **Licence:** choose one for the code (the data mirror is CC0).

## Decisions to make before pasting the prompt

The recommended option is first.

| Decision | Recommended | Alternative |
|---|---|---|
| Deck format | `.pptx` built by `python-pptx` from a Markdown outline (new dependency in a `docs` extra; needs approval) | Markdown outline and speaker notes only; Aman builds the slides by hand in PowerPoint or Google Slides |
| Report format | Markdown sections assembled into `reports/m6/technical_report.md`; PDF through pandoc if it is installed | Markdown only |
| Code licence | MIT | Apache-2.0, or none (all rights reserved) |
| Demo inputs | Synthetic, hand-written complaints in `demo/examples.json` (no real narratives on screen) | Real narratives with complaint IDs (avoid: the rule "never print narratives" stays simpler) |
| Demo fallback | Local `docker compose up` on the presenter's laptop, plus a screen recording made at rehearsal | Recording only |

## Owners (two people)

| Owner | Area | Main files |
|---|---|---|
| P3 Udita | Analysis chapters, limits, viva Q&A, business case | `reports/m6/sections/00_summary.md`, `01_problem.md`, `02_data.md`, `03_experiments.md`, `04_modeling.md`, `05_evaluation.md`, `07_limitations_ethics.md`; `docs/m6/business_case.md` (SPEC A5 formula with measured coverage and stated assumptions); `docs/m6/viva_prep.md` (every SPEC C14 question answered with numbers and sources); `docs/m6/resume_bullets.md` (SPEC C15, measured numbers only); crib sheets `docs/m6/viva/data.md`, `docs/m6/viva/experiments.md`, `docs/m6/viva/modeling.md` |
| P4 Aman | Deployment chapter, conclusion, repo, report tooling, demo, deck | `reports/m6/sections/06_deployment_monitoring.md`, `08_conclusion.md`; `scripts/build_report.py`; `scripts/check_numbers.py`; `README.md` rewrite; `docs/REPRODUCE.md`; `docs/m6/demo_script.md` (timed run sheet, fallback plan, rehearsal log); `demo/examples.json`; `docs/m6/deck_outline.md` (slides and speaker notes), `scripts/build_deck.py` and `reports/m6/ComplaintIQ_deck.pptx` (if approved); `.github/CODEOWNERS` with real usernames; CI badge; `LICENSE`; crib sheet `docs/m6/viva/deployment.md` |

## Stage order (reviewer is always the other person)

| Step | Owner | Branch | Depends on | Reviewer |
|---|---|---|---|---|
| 1 | Aman (P4) | `chore/m6-report-tooling` (`build_report.py`, `check_numbers.py`, sections folder skeleton) | tag `m5` | Udita |
| 2 | Udita (P3) | `docs/m6-problem-data-experiments` (sections 00-03, business case) | 1 | Aman |
| 3 | Udita (P3) | `docs/m6-modeling-evaluation-viva` (sections 04, 05, 07, viva prep, resume bullets, three crib sheets) | 1 | Aman |
| 4 | Aman (P4) | `docs/m6-deployment-repo` (section 06, 08, README, REPRODUCE, CODEOWNERS, LICENSE, deployment crib sheet) | 1 | Udita |
| 5 | Aman (P4) | `docs/m6-demo-deck` (demo script and examples, deck outline, deck) | 2-4 (the deck quotes their numbers) | Udita |
| 6 | Aman (P4) | `docs/m6-assembled-report` (`technical_report.md`, `number_check.md`) | 2-5 | Udita |
| 7 | Udita (P3) | `docs/m6-commit-plan` → tag `m6` | 6 | Aman |

## Design notes

- **`check_numbers.py`** enforces "no invented results". It lists every number in the report, deck outline, README, viva prep and resume bullets that does not appear in a source file under `reports/`, `docs/data_provenance.md` or `reports/experiments/`. Years, section numbers and lines marked `[assumption]` or `[target]` are excluded. The assembled report fails the check while that list is non-empty.
- **Labelled numbers:** every number is tagged **val**, **val-B (held-out)**, **test (one-shot)**, **target** or **assumption**, so a target never reads as a result (SPEC header note).
- **Crib sheets per stage, not per person:** with two builders and four viva members, the definition of done ("every member can explain every stage") needs a short sheet per stage that anyone can learn. The rehearsal log in `docs/m6/demo_script.md` records who explained which stage.

## M6 prompt

Paste this into a new Claude Code session after M5 is merged and tagged, and Udita has run `git switch main && git pull origin main && git switch -c import/m6-files` in `~/Desktop/complaintiq`. Fill in the `<...>` line first.

```text
Use /Users/udita/Desktop/complaintiq/.venv/bin/python for every Python command (e.g. `make test PYTHON=.venv/bin/python`). Confirm with `pwd` and `git branch --show-current` that you are in ~/Desktop/complaintiq on import/m6-files.
DECK: <python-pptx approved | outline only>   LICENCE: <MIT | Apache-2.0 | none>
TEAM: M6 is built by two people only: P3 Udita (@udita-0707) and P4 Aman (@AmanKumar1411). Each reviews the other's pull requests. All four members (also P1 Kalash @kkt04 and P2 Dally @astro-dally) sit the viva.

Read CLAUDE.md, docs/SPEC.md (all of Part A, B3, B7, C5, C6, C12, C13, C14, C15) and docs/M6_PLAN.md. Do NOT run git add, commit, push or tag. Do not add or change dependencies without asking (python-pptx only if approved above; ask before pandoc or anything else). Never print narratives or raw rows; aggregates and complaint_ids only. No new model training, calibration, evaluation or test-split reads in this session.

GOAL
Build ALL of M6 (technical report, GitHub repo, live demo, business deck, viva preparation) in this session from the results of M1-M5. Definition of done: demo rehearsed; every member can explain every stage. Branch import/m6-files was created from origin/main after M5 was merged and tagged m5. Then produce a commit plan for the two owners covering only the M6 files.

PREFLIGHT (stop and tell me if any fails)
1. Branch is import/m6-files, `git diff origin/main` is empty, make test and make lint pass with PYTHON=.venv/bin/python. Record `git rev-parse --short origin/main` as BASE_REF.
2. Inventory the sources and report which exist and which are TODO: reports/m2_data_stats.md, docs/data_provenance.md, docs/data_card.md, reports/m3/model_comparison.md, reports/m4/{evaluation_report,calibration_report,error_analysis,robustness_report,improvement_iterations,inference_benchmark,api_latency,test_results}.md, reports/m5/{deployment,load_test,failure_tests,drift_report}.md, docs/monitoring_plan.md, docs/security.md, configs/final_model.yaml, reports/experiments/**/*.csv. Continue if some are missing, but every statement that depends on them becomes TODO; tell me the list.
3. Read reports/experiments/transformer.csv: if it has no full (non-smoke) run, the report must say the transformer was not trained at scale, and must not claim it beat the baseline.

HARD RULES
- NO NEW RESULTS. Every number in any M6 file is copied from a source in preflight step 2. Label each number as val, val-B (held-out), test (one-shot), target or assumption. Targets and assumptions are never presented as results (SPEC header note). Negative results are reported (e.g. tau precision 0.9498 vs target 0.95, transformer status, missed targets).
- THE TEST SPLIT STAYS CLOSED. Test numbers come only from reports/m4/test_results.md. Do not run final_test_eval.py.
- No complaint narratives in any file, slide or demo input; demo inputs are synthetic.
- No file edits outside the owner lists below without saying so in the report. Do not change code behaviour; M6 code is report/deck/number tooling only.

BUILD BY OWNER
P3 (Udita): analysis chapters, limitations, viva Q&A, business case
- reports/m6/sections/00_summary.md (abstract with headline numbers), 01_problem.md (SPEC A1-A4, users, scope), 02_data.md (from docs/data_card.md: provenance, funnel, labels, priority proxy, splits, drift, privacy), 03_experiments.md (M3 runs, convergence reruns, selection on val, experiment-log schema), 04_modeling.md (model family choice, transformer status, calibration T and ECE before/after, gate tau/coverage/precision, priority threshold, vocabulary study, ONNX/int8 status), 05_evaluation.md (val and test headline with CIs, per-class highlights, slices, robustness, iterations, error taxonomy with shares), 07_limitations_ethics.md (proxy priority label, taxonomy drift, label noise, credit-reporting shift, regex-only PII, human-in-the-loop and no adverse customer outcomes, threats to validity: val reused for model selection, single seed for the baseline, free-tier latency).
- docs/m6/business_case.md: SPEC A5 formula `complaints/day x auto-route coverage x minutes saved` with coverage from test_results.md (or val-B, labelled, if test is TODO) and the other inputs marked [assumption]; a sensitivity table over the assumptions.
- docs/m6/viva_prep.md: every SPEC C14 question with a 3-5 sentence answer, numbers and source paths; plus the 10 hardest follow-ups you can anticipate, with answers.
- docs/m6/resume_bullets.md: SPEC C15 bullets filled only with measured numbers, each with its source.
- Crib sheets (one page each: what, why, key numbers, likely questions) docs/m6/viva/data.md (M2), experiments.md (M3), modeling.md (M4).
P4 (Aman): deployment chapter, conclusion, repo, report tooling, demo, deck
- scripts/build_report.py: assembles reports/m6/sections/*.md (sorted) into reports/m6/technical_report.md with a generated table of contents and a sources appendix; optional PDF via pandoc only if installed and approved.
- scripts/check_numbers.py: extracts every number from the M6 documents (sections, technical_report.md, deck outline, README, viva prep, resume bullets, business case) and lists those not found in any source file; ignores years, section/figure numbers and numbers on lines marked [assumption] or [target]; exits non-zero if anything is unmatched; writes reports/m6/number_check.md. tests/test_check_numbers.py (synthetic files).
- reports/m6/sections/06_deployment_monitoring.md (architecture as built, API, failure handling results, local and public load test, monitoring plan and drift results, security) and 08_conclusion.md (what worked, what did not, next steps).
- README.md rewrite: what it is, results table (labelled), demo URL, quickstart, reproduce commands per milestone, repo layout, limitations, team table; keep existing facts. docs/REPRODUCE.md: commands from raw data to deployed API, expected run ids and where each number lives; note what needs a GPU.
- demo/examples.json: 6-8 synthetic complaints that show AUTO route, HUMAN_REVIEW (low confidence), fraud override, PII scrubbing, a too-short 400, and feedback. docs/m6/demo_script.md: timed 5-7 minute run sheet (who speaks, what is clicked, expected output), live URL and the local docker fallback, pre-demo checklist (warm-up request, /health, model_version), recording instructions, rehearsal log table (date, duration, issues, who explained which stage).
- docs/m6/deck_outline.md: 10-12 slides (problem, users, data, approach, results, gate and business value, demo, deployment and monitoring, limitations, next steps, team) with speaker notes; numbers labelled. If python-pptx is approved: scripts/build_deck.py generating reports/m6/ComplaintIQ_deck.pptx from the outline with figures from reports/; otherwise leave the outline and say so.
- .github/CODEOWNERS: replace the placeholders with real usernames (@kkt04, @astro-dally, @udita-0707, @AmanKumar1411) for the paths each person owns from M1-M4, and @udita-0707 / @AmanKumar1411 for the M5/M6 paths; add LICENSE per the choice above; CI badge in README.
- Crib sheet docs/m6/viva/deployment.md (M5).

RUNS (this machine)
Only: scripts/build_report.py, scripts/check_numbers.py, scripts/build_deck.py (if approved), make test, make lint. Optionally one smoke request against the public URL from reports/m5/deployment.md (one /health and one synthetic /v1/triage; record time and model_version in docs/m6/demo_script.md). No training or evaluation runs.

CHECKS
make test and make lint green; scripts/check_numbers.py exits 0 (or every remaining unmatched number is listed in the report as TODO with a reason); grep confirms no M6 file contains narrative text or reads test.parquet; `git status --short` shows no data, models, *_LOCAL.csv or .env files.

COMMIT PLAN
Write docs/COMMIT_PLAN_M6.md and scripts/commit_plan_m6/p3.sh (Udita) and p4.sh (Aman) in the same style as scripts/commit_plan_m5/*.sh, taking files from origin/import/m6-files. Cover ONLY files that differ from BASE_REF (`git diff --name-status BASE_REF` plus untracked), one owner each (P3 or P4 only), UNASSIGNED listed with a proposal. List separately every file changed in BOTH M6 and an earlier milestone (README.md, CODEOWNERS, ...) and say which of the two owners commits it. Use the stage order in docs/M6_PLAN.md (branch names, dependencies; the reviewer is always the other person). The scripts refuse to run until docs/COMMIT_PLAN_M5.md is on origin/main. Add the Co-authored-by note and the final `git tag m6` command.

FINAL REPORT
Files created and changed per owner, the number-check result, the list of TODO statements and which source they wait for, deviations from this prompt, the rehearsal checklist each of the four members must complete before the viva, and the exact commands Udita and Aman should run next (including building the deck/PDF and tagging m6). Nothing committed, pushed or tagged.
```
