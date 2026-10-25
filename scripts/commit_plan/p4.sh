#!/usr/bin/env bash
# Commit plan for P4 (deployment lead). Generated from docs/COMMIT_PLAN.md; see that file first.
# Usage: scripts/commit_plan/p4.sh <stage>     stages: m1 m2
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
  m1)
    BRANCH='feat/scaffold'
    # step 3 of the merge order; depends on step(s): 1 (Dockerfile copies README.md), 2 (API reads model.yaml, thresholds.yaml)
    run_stage() {
      commit_files 'build: add pyproject, Makefile and ignore files' \
        pyproject.toml \
        Makefile \
        .gitignore \
        .dockerignore
      commit_files 'feat: add package skeleton and config loader' \
        src/complaintiq/__init__.py \
        src/complaintiq/config.py \
        src/complaintiq/data/__init__.py \
        src/complaintiq/eval/__init__.py \
        src/complaintiq/models/__init__.py \
        src/complaintiq/monitoring/__init__.py \
        src/complaintiq/privacy/__init__.py
      commit_files 'feat(serving): add triage API with stub predictor, confidence gate and router' \
        src/complaintiq/serving/__init__.py \
        src/complaintiq/serving/app.py \
        src/complaintiq/serving/schemas.py \
        src/complaintiq/serving/predictor.py \
        src/complaintiq/serving/gate.py \
        src/complaintiq/serving/router.py \
        configs/routing.yaml
      # UNASSIGNED in the plan, proposed owner P4: tests/test_gate.py (confirm first)
      commit_files 'test(serving): add confidence gate and API tests' \
        tests/test_gate.py \
        tests/test_api.py
      commit_files 'ci: add Dockerfile, compose file and CI workflow' \
        docker/Dockerfile \
        docker/docker-compose.yml \
        .github/workflows/ci.yml
    }
    ;;
  m2)
    BRANCH='feat/data-pipeline'
    # step 8 of the merge order; depends on step(s): 4, 5, 6 (build.py imports analysis, figures, stats and privacy.pii)
    run_stage() {
      commit_files 'feat(data): add pipeline and build entry points for make data' \
        src/complaintiq/data/pipeline.py \
        src/complaintiq/data/build.py
      commit_files 'test(serving): check routing covers every taxonomy product' \
        tests/test_router.py
      # UNASSIGNED in the plan, proposed owner P4: .github/CODEOWNERS scripts/commit_plan/p1.sh scripts/commit_plan/p2.sh scripts/commit_plan/p3.sh scripts/commit_plan/p4.sh (confirm first)
      commit_files 'chore: add CODEOWNERS and per-person commit scripts' \
        .github/CODEOWNERS \
        scripts/commit_plan/p1.sh \
        scripts/commit_plan/p2.sh \
        scripts/commit_plan/p3.sh \
        scripts/commit_plan/p4.sh
    }
    ;;
  *) die "usage: $0 <stage>   (stages: m1 m2)" ;;
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
