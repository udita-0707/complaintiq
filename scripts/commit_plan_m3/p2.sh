#!/usr/bin/env bash
# M3 commit plan for P2 (Dally, metrics, baseline, reports). Generated from docs/COMMIT_PLAN_M3.md; read that file first.
# Usage: scripts/commit_plan_m3/p2.sh <stage>     stages: m3-metrics m3-baseline
# Run each stage only after every stage it depends on has been merged into main.
# Optional: COAUTHOR="Name <email>" adds a Co-authored-by trailer to every commit of the run
# (only for someone who really helped on these files).
# Run it from a copy outside the clone (cp -r scripts/commit_plan_m3 /tmp/), with your clone as
# the current directory: these scripts are not on main until step 6.
# This script never pushes, never force-updates and never sets --author.
set -euo pipefail

BLOCKED_EMAIL_DOMAINS="${BLOCKED_EMAIL_DOMAINS:-valura.ai}"   # space-separated
REPO_URL="https://github.com/udita-0707/complaintiq"
IMPORT_REF="origin/import/m3-files"

die() { echo "ERROR: $*" >&2; exit 1; }

STAGE="${1:-}"
case "$STAGE" in
  m3-metrics)
    BRANCH='feat/m3-metrics'
    # step 2 of the M3 merge order; depends on: 1 (merge order only; no code dependency)
    run_stage() {
      commit_files 'feat(eval): add metrics with fixed-label-set macro-F1, bootstrap CI, slices and priority metrics' \
        src/complaintiq/eval/metrics.py
      commit_files 'feat(eval): add CSV experiment log with header migration' \
        src/complaintiq/eval/tracking.py
      commit_files 'test(eval): add metrics and experiment-log tests' \
        tests/test_metrics.py
    }
    ;;
  m3-baseline)
    BRANCH='feat/m3-baseline'
    # step 3 of the M3 merge order; depends on: 1 (training_data) and 2 (metrics, tracking)
    run_stage() {
      commit_files 'feat(models): add TF-IDF baseline with SGD variants, Complement NB and val rescoring' \
        configs/baseline.yaml \
        src/complaintiq/models/baseline.py
      commit_files 'test(models): add baseline, Complement NB and convergence tests on synthetic text' \
        tests/test_baseline.py
      commit_files 'feat(scripts): add experiment-log comparison with superseded rows and ranking' \
        scripts/compare_runs.py
      commit_files 'docs(m3): add experiment logs, baseline val report and model comparison' \
        reports/experiments/baseline.csv \
        reports/experiments/transformer.csv \
        reports/m3/baseline_val_report.md \
        reports/m3/model_comparison.md
    }
    ;;
  *) die "usage: $0 <stage>   (stages: m3-metrics m3-baseline)" ;;
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
  || die "$IMPORT_REF does not exist. Push the full M3 tree to branch import/m3-files first (see docs/COMMIT_PLAN_M3.md)."
git rev-parse --verify --quiet "origin/main^{commit}" >/dev/null || die "origin/main does not exist"
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
echo "  5. After merge: git switch main && git pull origin main, then run the next stage in docs/COMMIT_PLAN_M3.md."
