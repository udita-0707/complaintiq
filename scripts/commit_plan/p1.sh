#!/usr/bin/env bash
# Commit plan for P1 (data lead). Generated from docs/COMMIT_PLAN.md; see that file first.
# Usage: scripts/commit_plan/p1.sh <stage>     stages: m2-core m2-tests
# Run each stage only after every stage it depends on has been merged into main.
# Optional: COAUTHOR="Name <email>" adds a Co-authored-by trailer to every commit of the run
# (only for someone who really helped on these files).
# Run it from a copy outside the clone (cp -r scripts/commit_plan /tmp/), with your clone as
# the current directory: these scripts are not on main until step 8.
# This script never pushes, never force-updates and never sets --author.
set -euo pipefail

BLOCKED_EMAIL_DOMAINS="${BLOCKED_EMAIL_DOMAINS:-valura.ai}"   # space-separated
REPO_URL="https://github.com/udita-0707/complaintiq"
IMPORT_REF="origin/import/all-files"

die() { echo "ERROR: $*" >&2; exit 1; }

STAGE="${1:-}"
case "$STAGE" in
  m2-core)
    BRANCH='feat/data-core'
    # step 4 of the merge order; depends on step(s): 3
    run_stage() {
      commit_files 'feat(data): add data config and raw data preparation script' \
        configs/data.yaml \
        scripts/prepare_raw_data.py \
        docs/data_provenance.md
      commit_files 'feat(data): add column-limited loader and text cleaning' \
        src/complaintiq/data/load.py \
        src/complaintiq/data/clean.py
      commit_files 'feat(data): add product and issue taxonomy mappings' \
        src/complaintiq/data/taxonomy.py \
        configs/product_mapping.yaml \
        configs/issue_mapping.yaml
      commit_files 'feat(data): add priority labels and time/random splits' \
        src/complaintiq/data/priority.py \
        configs/severity_issues.yaml \
        src/complaintiq/data/split.py
    }
    ;;
  m2-tests)
    BRANCH='feat/data-tests'
    # step 7 of the merge order; depends on step(s): 4 and 6 (two tests in test_data.py import data.analysis)
    run_stage() {
      commit_files 'test(data): add cleaning, priority, split and taxonomy tests' \
        tests/test_data.py
    }
    ;;
  *) die "usage: $0 <stage>   (stages: m2-core m2-tests)" ;;
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
  || die "$IMPORT_REF does not exist. Push the full repo to branch import/all-files first (see docs/COMMIT_PLAN.md)."
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
echo "  5. After merge: git switch main && git pull origin main, then run the next stage."
