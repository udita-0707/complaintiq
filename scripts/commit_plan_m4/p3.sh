#!/usr/bin/env bash
# M4 commit plan for P3 (Udita, calibration and inference benchmark). Generated from docs/COMMIT_PLAN_M4.md; read that file first.
# Usage: scripts/commit_plan_m4/p3.sh <stage>     stages: m4-calibration m4-benchmark
# Run these scripts only after ALL M3 stages (docs/COMMIT_PLAN_M3.md) are merged into main,
# and each stage only after every stage it depends on has been merged into main.
# Optional: COAUTHOR="Name <email>" adds a Co-authored-by trailer to every commit of the run
# (only for someone who really helped on these files).
# Run it from a copy outside the clone (cp -r scripts/commit_plan_m4 /tmp/), with your clone as
# the current directory: these scripts are not on main until step 7.
# This script never pushes, never force-updates and never sets --author.
set -euo pipefail

BLOCKED_EMAIL_DOMAINS="${BLOCKED_EMAIL_DOMAINS:-valura.ai}"   # space-separated
REPO_URL="https://github.com/udita-0707/complaintiq"
IMPORT_REF="origin/import/m4-files"
# The last M3 stage adds this file to main; M4 stages need all of M3 on main first.
M3_DONE_FILE="docs/COMMIT_PLAN_M3.md"

die() { echo "ERROR: $*" >&2; exit 1; }

STAGE="${1:-}"
case "$STAGE" in
  m4-calibration)
    BRANCH='feat/m4-calibration'
    # step 2 of the M4 merge order; depends on: 1 (order only)
    run_stage() {
      commit_files 'feat(config): add M4 evaluation config with val-A/val-B split and run settings' \
        configs/eval.yaml
      commit_files 'feat(models): add temperature scaling, ECE, tau and priority threshold on val-A' \
        src/complaintiq/models/calibrate.py
      commit_files 'test(models): cover calibration, val split, tau and threshold choice on synthetic data' \
        tests/test_calibrate.py
      commit_files 'feat(config): set tau, temperatures and priority threshold from val-A calibration' \
        configs/thresholds.yaml
      commit_files 'docs(m4): add calibration report, reliability and coverage figures, run log' \
        reports/m4/calibration_report.md \
        reports/m4/figures/reliability_product.png \
        reports/m4/figures/reliability_issue.png \
        reports/m4/figures/coverage_precision_product.png \
        reports/m4/results/calibration.json \
        reports/experiments/m4/calibration.csv
    }
    ;;
  m4-benchmark)
    BRANCH='feat/m4-inference-benchmark'
    # step 5 of the M4 merge order; depends on: 4 (BaselinePredictor temperatures)
    run_stage() {
      commit_files 'feat(scripts): add CPU inference benchmark and vocabulary-size study' \
        scripts/benchmark_inference.py
      commit_files 'docs(m4): add inference benchmark report and run log' \
        reports/m4/inference_benchmark.md \
        reports/m4/results/benchmark.json \
        reports/experiments/m4/benchmark.csv
    }
    ;;
  *) die "usage: $0 <stage>   (stages: m4-calibration m4-benchmark)" ;;
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
  || die "$IMPORT_REF does not exist. Push the full M4 tree to branch import/m4-files first (see docs/COMMIT_PLAN_M4.md)."
git rev-parse --verify --quiet "origin/main^{commit}" >/dev/null || die "origin/main does not exist"
git cat-file -e "origin/main:$M3_DONE_FILE" 2>/dev/null \
  || die "M3 is not fully merged into main ($M3_DONE_FILE missing). Finish docs/COMMIT_PLAN_M3.md first."
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
  printf '  %s\n' "$@"
  git add -- "$@"
  git commit -m "$msg" ${TRAILER[@]+"${TRAILER[@]}"}
}

run_stage
echo
echo "Done. Branch $BRANCH is local only. Nothing was pushed."
echo "Next steps:"
echo "  1. Run the tests: make test   (and make lint)"
echo "  2. Push:          git push -u origin $BRANCH"
echo "  3. Open a pull request: $REPO_URL/compare/main...$BRANCH"
echo "     base: main, compare: $BRANCH, title: the first commit message above."
echo "  4. Ask the CODEOWNERS reviewer to review; merge only when CI is green."
echo "  5. After merge: git switch main && git pull origin main, then run the next stage in docs/COMMIT_PLAN_M4.md."
