# M6 commit plan (report, repository, demo, deck, viva)

All M6 files were produced in one shared working session on top of M5 (`main` after the M5 merge
and tag `m5`). Only **P3 Udita (@udita-0707)** and **P4 Aman (@AmanKumar1411)** build, commit and
review M6; the reviewer is always the other person. All four members sit the viva. Each person
commits only their own files with `scripts/commit_plan_m6/pN.sh <stage>`, under their own git
identity. No script pushes, uses `--author` or `--force`. The process is the same as
`docs/COMMIT_PLAN_M5.md`.

## Before you start

- **M5 must be merged and tagged `m5`.** Every M6 script checks that `docs/COMMIT_PLAN_M5.md` and
  `reports/m5/deployment.md` are on `origin/main`.
- **The M5 numbers are already in.** Section 6 of the report, the README, the crib sheets and the
  deck quote the merged `reports/m5/` (local container; no public deployment). If an M5 report
  changes, rerun `make report` on the import branch and push the result before stage 6.
- **Each stage checks its dependencies** on `origin/main` and refuses to run otherwise.

## How it works

1. Udita, on her Mac, after `m5`: `git switch main && git pull origin main && git switch -c
   import/m6-files`, copy the M6 files in (the handoff zip's `apply_m6_files.sh` checks that exactly
   the listed files changed), run `make test lint report` (`unmatched numbers: 0`; it regenerates
   only files that are already in the list), commit once and
   `git push -u origin import/m6-files`. The branch is never merged.
2. Stages are merged into `main` in the order below. Each branches from the latest `origin/main`,
   takes only its owner's files from `origin/import/m6-files`, and commits them with the messages
   below. Copy `scripts/commit_plan_m6/` outside the clone and run `/tmp/commit_plan_m6/pN.sh
   <stage>` from the clone.
3. `BLOCKED_EMAIL_DOMAINS` (default `valura.ai`) stops a commit under a work email.

**Co-authors.** `COAUTHOR="Name <email>"` adds a trailer; Kalash or Dally only if they really
helped on a file.

## Merge order

| Step | Owner | Branch | Command | Depends on | Reviewer |
|---|---|---|---|---|---|
| 1 | P4 Aman | `chore/m6-report-tooling` | `p4.sh m6-report-tooling` | tag `m5` | P3 Udita |
| 2 | P3 Udita | `docs/m6-problem-data-experiments` | `p3.sh m6-problem-data` | 1 | P4 Aman |
| 3 | P3 Udita | `docs/m6-modeling-evaluation-viva` | `p3.sh m6-modeling-viva` | 1 | P4 Aman |
| 4 | P4 Aman | `docs/m6-deployment-repo` | `p4.sh m6-deployment-repo` | 1 | P3 Udita |
| 5 | P4 Aman | `docs/m6-demo-deck` | `p4.sh m6-demo-deck` | 2-4 | P3 Udita |
| 6 | P4 Aman | `docs/m6-assembled-report` | `p4.sh m6-assembled-report` | 2-5 | P3 Udita |
| 7 | P3 Udita | `docs/m6-commit-plan` | `p3.sh m6-commit-plan`, then `git tag m6` | 6 | P4 Aman |

Steps 2, 3 and 4 are independent of each other once step 1 is merged.

## Files, owners and commit messages

| Step | File | Owner | Commit message |
|---|---|---|---|
| 1 | `scripts/check_numbers.py` | P4 | `feat(scripts): add number check that traces every M6 number to a source file` |
| 1 | `scripts/build_report.py` | P4 | `feat(scripts): add report builder with derived numbers and assembly` |
| 1 | `tests/test_report_tools.py` | P4 | `test(scripts): cover number parsing, matching, exemptions and derived numbers` |
| 1 | `Makefile` | P4 | `build: add report and check-numbers Makefile targets` |
| 1 | `reports/m6/derived_numbers.md` | P4 | `docs(m6): add derived numbers computed from the M2-M4 reports` |
| 2 | `reports/m6/sections/00_summary.md` | P3 | `docs(m6): add summary, problem and data chapters` |
| 2 | `reports/m6/sections/01_problem.md` | P3 | (same commit) |
| 2 | `reports/m6/sections/02_data.md` | P3 | (same commit) |
| 2 | `reports/m6/sections/03_experiments.md` | P3 | `docs(m6): add experiments chapter` |
| 2 | `docs/m6/business_case.md` | P3 | `docs(m6): add business case with measured coverage and stated assumptions` |
| 3 | `reports/m6/sections/04_modeling.md` | P3 | `docs(m6): add modeling, evaluation and limitations chapters` |
| 3 | `reports/m6/sections/05_evaluation.md` | P3 | (same commit) |
| 3 | `reports/m6/sections/07_limitations_ethics.md` | P3 | (same commit) |
| 3 | `docs/m6/viva_prep.md` | P3 | `docs(m6): add viva preparation and resume bullets with measured numbers` |
| 3 | `docs/m6/resume_bullets.md` | P3 | (same commit) |
| 3 | `docs/m6/viva/data.md` | P3 | `docs(m6): add crib sheets for data, experiments and modeling` |
| 3 | `docs/m6/viva/experiments.md` | P3 | (same commit) |
| 3 | `docs/m6/viva/modeling.md` | P3 | (same commit) |
| 4 | `reports/m6/sections/06_deployment_monitoring.md` | P4 | `docs(m6): add deployment and monitoring chapter and conclusion` |
| 4 | `reports/m6/sections/08_conclusion.md` | P4 | (same commit) |
| 4 | `README.md` | P4 | `docs: rewrite README with results, quickstart, layout and team` |
| 4 | `docs/REPRODUCE.md` | P4 | `docs: add reproduction guide` |
| 4 | `.github/CODEOWNERS` | P4 | `chore: set real code owners and add the MIT licence` |
| 4 | `LICENSE` | P4 | (same commit) |
| 4 | `docs/m6/viva/deployment.md` | P4 | `docs(m6): add deployment crib sheet` |
| 5 | `docs/m6/demo_script.md` | P4 | `docs(m6): add demo run sheet and synthetic demo inputs` |
| 5 | `demo/examples.json` | P4 | (same commit) |
| 5 | `docs/m6/deck_outline.md` | P4 | `docs(m6): add deck outline and the presentation deck` |
| 5 | `reports/m6/ComplaintIQ_deck.pptx` | P4 | (same commit) |
| 6 | `reports/m6/technical_report.md` | P4 | `docs(m6): add assembled technical report and number check` |
| 6 | `reports/m6/number_check.md` | P4 | (same commit) |
| 7 | `docs/COMMIT_PLAN_M6.md` | P3 | `docs: add M6 commit plan and per-person scripts` |
| 7 | `scripts/commit_plan_m6/p3.sh` | P3 | (same commit) |
| 7 | `scripts/commit_plan_m6/p4.sh` | P3 | (same commit) |

## Counts

| Owner | Files |
|---|---|
| P3 Udita | 16 |
| P4 Aman | 18 |
| UNASSIGNED | 0 |
| Total | 34 |

## Flags

- **Derived numbers merge first.** `reports/m6/derived_numbers.md` depends only on the M2-M4
  reports, so it merges in stage 1; from then on `make check-numbers` passes on every stage.
- **Stage 6 must be rebuilt if anything earlier changed.** `technical_report.md` and
  `number_check.md` are generated by `make report` from the sections and the source reports. If a section or a source report changes in review, rerun `make report` on the
  import branch, push, and only then run stage 6.
- **Licence:** MIT was chosen in the session (the M6 plan's recommendation). Change `LICENSE` and
  the README line before stage 4 if the team prefers Apache-2.0 or no licence.
- **The number check proves presence, not correctness.** A number passes when some source contains
  it; reviewers still check that each number matches the source the text cites.
- **The deck** was built outside the Python project (Node.js and pptxgenjs, not project
  dependencies). It already carries the M5 numbers; edit it directly in PowerPoint if anything
  changes (`docs/m6/deck_outline.md` lists what each slide quotes).
- **Rehearsal:** the M6 definition of done needs the rehearsal log in `docs/m6/demo_script.md`
  filled (who explained which stage). Fill it after rehearsing and commit it with a small follow-up
  pull request before tagging `m6`, or say in the stage 7 pull request that it is pending.

## Files changed in both M6 and an earlier milestone

| File | Earlier owner | M6 owner | M6 step |
|---|---|---|---|
| `Makefile` | P4 (M1-M5) | P4 | 1 |
| `README.md` | P2 (M1) | P4 | 4 |
| `.github/CODEOWNERS` | P4 (M1, placeholders) | P4 | 4 |

## Deviations from docs/M6_PLAN.md

- No `scripts/build_deck.py` and no `docs` extra: the deck was produced in the session with
  pptxgenjs, so no new Python dependency was needed.
- `check_numbers.py` also reads `docs/data_card.md` (itself copied from the M2 reports),
  `configs/*.yaml` (frozen thresholds) and `docs/SPEC.md` (targets and constants) as sources, skips
  HTTP status codes, and counts `reports/m6/derived_numbers.md` as a source: computed values (the
  business case, error-share sums, the test score without the unseen class) are calculated there
  from source files, with formulas, instead of being typed into the prose.
- `tests/test_report_tools.py` was added for the two report scripts.
- The PDF is optional (`python scripts/build_report.py --pdf`, needs pandoc and a PDF engine).

## After step 7

```bash
git switch main && git pull origin main && git tag m6 && git push origin m6
```
