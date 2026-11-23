#!/usr/bin/env bash
# M6 commit plan for P3 (Udita: problem, data, experiments, modeling and evaluation chapters, business case, viva material, commit plan). Generated from docs/COMMIT_PLAN_M6.md; read that file first.
# Usage: scripts/commit_plan_m6/p3.sh <stage>     stages: m6-problem-data m6-modeling-viva m6-commit-plan
# Run these scripts only after M5 is merged into main and tagged m5, and each stage only after
# every stage it depends on has been merged into main (checked below).
# Optional: COAUTHOR="Name <email>" adds a Co-authored-by trailer to every commit of the run
# (only for someone who really helped on these files; Kalash or Dally only if they did).
# Run it from a copy outside the clone (cp -r scripts/commit_plan_m6 /tmp/), with your clone as
# the current directory: these scripts are not on main until step 7.
# This script never pushes, never force-updates and never sets --author.
set -euo pipefail

BLOCKED_EMAIL_DOMAINS="${BLOCKED_EMAIL_DOMAINS:-valura.ai}"   # space-separated
REPO_URL="https://github.com/udita-0707/complaintiq"
IMPORT_REF="origin/import/m6-files"
# The last M5 stage adds this file to main; M6 stages need all of M5 on main first.
PREV_DONE_FILES="docs/COMMIT_PLAN_M5.md reports/m5/deployment.md"

die() { echo "ERROR: $*" >&2; exit 1; }

STAGE="${1:-}"
case "$STAGE" in
  m6-problem-data)
    BRANCH='docs/m6-problem-data-experiments'
    # step 2 of the M6 merge order; depends on: 1 (report tooling)
    NEED_ON_MAIN="scripts/build_report.py scripts/check_numbers.py"
    run_stage() {
      commit_files 'docs(m6): add summary, problem and data chapters' \
        reports/m6/sections/00_summary.md \
        reports/m6/sections/01_problem.md \
        reports/m6/sections/02_data.md
      commit_files 'docs(m6): add experiments chapter' \
        reports/m6/sections/03_experiments.md
      commit_files 'docs(m6): add business case with measured coverage and stated assumptions' \
        docs/m6/business_case.md
    }
    ;;
  m6-modeling-viva)
    BRANCH='docs/m6-modeling-evaluation-viva'
    # step 3 of the M6 merge order; depends on: 1 (report tooling)
    NEED_ON_MAIN="scripts/build_report.py"
    run_stage() {
      commit_files 'docs(m6): add modeling, evaluation and limitations chapters' \
        reports/m6/sections/04_modeling.md \
        reports/m6/sections/05_evaluation.md \
        reports/m6/sections/07_limitations_ethics.md
      commit_files 'docs(m6): add viva preparation and resume bullets with measured numbers' \
        docs/m6/viva_prep.md \
        docs/m6/resume_bullets.md
      commit_files 'docs(m6): add crib sheets for data, experiments and modeling' \
        docs/m6/viva/data.md \
        docs/m6/viva/experiments.md \
        docs/m6/viva/modeling.md
    }
    ;;
  m6-commit-plan)
    BRANCH='docs/m6-commit-plan'
    # step 7 of the M6 merge order; depends on: 6 (assembled report)
    NEED_ON_MAIN="reports/m6/technical_report.md reports/m6/number_check.md"
    run_stage() {
      commit_files 'docs: add M6 commit plan and per-person scripts' \
        docs/COMMIT_PLAN_M6.md \
        scripts/commit_plan_m6/p3.sh \
        scripts/commit_plan_m6/p4.sh
    }
    ;;
  *) die "usage: $0 <stage>   (stages: m6-problem-data m6-modeling-viva m6-commit-plan)" ;;
esac
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || die "run this inside your clone of $REPO_URL"
cd "$(git rev-parse --show-toplevel)"

NAME="$(git config user.name || true)"
EMAIL="$(git config user.email || true)"
[ -n "$EMAIL" ] || die "git config user.email is empty; set your own email first"
[ -n "$NAME" ] || die "git config user.name is empty; set your own name first"
EMAIL_LC="$(printf '%s' "$EMAIL" | tr '[:upper:]' '[:lower:]')"
for d in $BLOCKED_EMAIL_DOMAINS; do
  d="$(printf '%s' "$d" | tr '[:upper:]' '[:lower:]')"
  case "$EMAIL_LC" in
    *"@$d"|*".$d") die "user.email '$EMAIL' uses blocked domain '$d'; set your personal email" ;;
  esac
done
echo "Committing as: $NAME <$EMAIL>"

[ -z "$(git status --porcelain --untracked-files=no)" ] || die "working tree has uncommitted changes; commit or stash them first"

git fetch origin
git rev-parse --verify --quiet "$IMPORT_REF^{commit}" >/dev/null \
  || die "$IMPORT_REF does not exist. Push the full M6 tree to branch import/m6-files first (see docs/COMMIT_PLAN_M6.md)."
git rev-parse --verify --quiet "origin/main^{commit}" >/dev/null || die "origin/main does not exist"
for f in $PREV_DONE_FILES; do
  git cat-file -e "origin/main:$f" 2>/dev/null \
    || die "M5 is not merged into main ($f missing). Finish docs/COMMIT_PLAN_M5.md and tag m5 first."
done
# Earlier M5 stages this one depends on must be merged: a file, or file:text that must appear in it.
for need in $NEED_ON_MAIN; do
  f="${need%%:*}"; text=""; [ "$f" != "$need" ] && text="${need#*:}"
  git cat-file -e "origin/main:$f" 2>/dev/null \
    || die "an earlier M6 stage is not merged ($f missing on origin/main). See the merge order in docs/COMMIT_PLAN_M6.md."
  if [ -n "$text" ]; then
    git show "origin/main:$f" | grep -q "$text" \
      || die "an earlier M6 stage is not merged ($f on origin/main lacks '$text'). See docs/COMMIT_PLAN_M6.md."
  fi
done
git rev-parse --verify --quiet "refs/heads/$BRANCH" >/dev/null && die "local branch $BRANCH already exists"

git switch -c "$BRANCH" origin/main

TRAILER=()
[ -n "${COAUTHOR:-}" ] && TRAILER=(-m "Co-authored-by: $COAUTHOR")

commit_files() {
  local msg="$1"; shift
  local f
  for f in "$@"; do
    git cat-file -e "$IMPORT_REF:$f" 2>/dev/null || die "$f is not in $IMPORT_REF"
  done
  git checkout "$IMPORT_REF" -- "$@"
  echo
  echo "About to commit ($msg):"
  printf '  %s
' "$@"
  git add -- "$@"
  git commit -m "$msg" ${TRAILER[@]+"${TRAILER[@]}"}
}

run_stage
echo
echo "Done. Branch $BRANCH is local only. Nothing was pushed."
echo "Next steps:"
echo "  1. Run the checks: make test lint check-numbers   (must print 'unmatched numbers: 0')"
echo "  2. Push:          git push -u origin $BRANCH"
echo "  3. Open a pull request: $REPO_URL/compare/main...$BRANCH"
echo "     base: main, compare: $BRANCH, title: the first commit message above. Reviewer: Aman."
echo "  4. Merge only when CI is green."
if [ "$STAGE" = "m6-commit-plan" ]; then
  echo "  5. After merge, tag M6:  git switch main && git pull origin main && git tag m6 && git push origin m6"
else
  echo "  5. After merge: git switch main && git pull origin main, then run the next stage in docs/COMMIT_PLAN_M6.md."
fi
