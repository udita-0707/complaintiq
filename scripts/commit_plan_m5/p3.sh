#!/usr/bin/env bash
# M5 commit plan for P3 (Udita: input safety, request log, drift monitoring). Generated from docs/COMMIT_PLAN_M5.md; read that file first.
# Usage: scripts/commit_plan_m5/p3.sh <stage>     stages: m5-input-safety m5-request-log m5-drift
# Run these scripts only after the M4 close-out is on main (reports/m4/test_results.md), and each
# stage only after every stage it depends on has been merged into main (checked below).
# Optional: COAUTHOR="Name <email>" adds a Co-authored-by trailer to every commit of the run
# (only for someone who really helped on these files; Kalash or Dally only if they did).
# Run it from a copy outside the clone (cp -r scripts/commit_plan_m5 /tmp/), with your clone as
# the current directory: these scripts are not on main until step 7.
# This script never pushes, never force-updates and never sets --author.
set -euo pipefail

BLOCKED_EMAIL_DOMAINS="${BLOCKED_EMAIL_DOMAINS:-valura.ai}"   # space-separated
REPO_URL="https://github.com/udita-0707/complaintiq"
IMPORT_REF="origin/import/m5-files"
# The M4 close-out adds these files to main; M5 stages need them first.
M4_DONE_FILES="reports/m4/test_results.md docs/COMMIT_PLAN_M4.md"

die() { echo "ERROR: $*" >&2; exit 1; }

STAGE="${1:-}"
case "$STAGE" in
  m5-input-safety)
    BRANCH='feat/m5-input-safety'
    # step 2 of the M5 merge order; depends on: 1 (order only)
    NEED_ON_MAIN="src/complaintiq/config.py:project_root"
    run_stage() {
      commit_files 'feat(privacy): count redactions and residual PII hits; import polars lazily' \
        src/complaintiq/privacy/pii.py
      commit_files 'feat(serving): add input quality check for short, gibberish and non-English text' \
        src/complaintiq/serving/input_quality.py
      commit_files 'feat(serving): add body size limit, per-client rate limit and CORS origin checks' \
        src/complaintiq/serving/security.py
      commit_files 'feat(config): add input safety and security settings' \
        configs/safety.yaml
      commit_files 'test(serving): cover scrub counts, quality reasons and security middlewares' \
        tests/test_input_safety.py
      commit_files 'docs: add security and privacy notes (human in the loop, no adverse outcomes)' \
        docs/security.md
    }
    ;;
  m5-request-log)
    BRANCH='feat/m5-request-log'
    # step 3 of the M5 merge order; depends on: 1 (config.resolve_path), 2 (scrubbed text only reaches logging)
    NEED_ON_MAIN="src/complaintiq/config.py:resolve_path src/complaintiq/serving/input_quality.py"
    run_stage() {
      commit_files 'feat(serving): add SQLite audit log with feedback, correction rate and store-down buffer' \
        src/complaintiq/serving/request_log.py
      commit_files 'feat(config): add request log settings' \
        configs/request_log.yaml
      commit_files 'test(serving): cover audit rows, feedback linking, correction rate and failure injection' \
        tests/test_request_log.py
    }
    ;;
  m5-drift)
    BRANCH='feat/m5-drift-monitoring'
    # step 4 of the M5 merge order; depends on: 1 (config.resolve_path)
    NEED_ON_MAIN="src/complaintiq/config.py:resolve_path"
    run_stage() {
      commit_files 'feat(monitoring): add PSI/KL, confidence and input drift with a month-by-month val replay' \
        src/complaintiq/monitoring/drift.py \
        src/complaintiq/monitoring/__init__.py
      commit_files 'feat(config): add drift monitoring thresholds and replay settings' \
        configs/monitoring.yaml
      commit_files 'test(monitoring): cover drift statistics and a synthetic replay' \
        tests/test_drift.py
      commit_files 'docs: add monitoring plan with signals, thresholds, owners and playbooks' \
        docs/monitoring_plan.md
      commit_files 'docs(m5): add drift replay report and run log' \
        reports/m5/drift_report.md \
        reports/m5/results/drift.json \
        reports/experiments/m5/drift.csv
    }
    ;;
  *) die "usage: $0 <stage>   (stages: m5-input-safety m5-request-log m5-drift)" ;;
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
  || die "$IMPORT_REF does not exist. Push the full M5 tree to branch import/m5-files first (see docs/COMMIT_PLAN_M5.md)."
git rev-parse --verify --quiet "origin/main^{commit}" >/dev/null || die "origin/main does not exist"
for f in $M4_DONE_FILES; do
  git cat-file -e "origin/main:$f" 2>/dev/null \
    || die "the M4 close-out is not on main ($f missing). Finish Step 0 of docs/M5_PLAN.md first."
done
# Earlier M5 stages this one depends on must be merged: a file, or file:text that must appear in it.
for need in $NEED_ON_MAIN; do
  f="${need%%:*}"; text=""; [ "$f" != "$need" ] && text="${need#*:}"
  git cat-file -e "origin/main:$f" 2>/dev/null \
    || die "an earlier M5 stage is not merged ($f missing on origin/main). See the merge order in docs/COMMIT_PLAN_M5.md."
  if [ -n "$text" ]; then
    git show "origin/main:$f" | grep -q "$text" \
      || die "an earlier M5 stage is not merged ($f on origin/main lacks '$text'). See docs/COMMIT_PLAN_M5.md."
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
echo "     base: main, compare: $BRANCH, title: the first commit message above. Reviewer: Aman."
echo "  4. Merge only when CI is green."
echo "  5. After merge: git switch main && git pull origin main, then run the next stage in docs/COMMIT_PLAN_M5.md."
