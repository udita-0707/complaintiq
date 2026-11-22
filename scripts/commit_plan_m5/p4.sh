#!/usr/bin/env bash
# M5 commit plan for P4 (Aman: config groundwork, runtime and metrics, deployment, UI, load and failure tests, commit plan). Generated from docs/COMMIT_PLAN_M5.md; read that file first.
# Usage: scripts/commit_plan_m5/p4.sh <stage>     stages: m5-gitignore-config m5-runtime m5-ui-deploy m5-commit-plan
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
  m5-gitignore-config)
    BRANCH='chore/m5-gitignore-config'
    # step 1 of the M5 merge order; depends on: the M4 close-out only
    NEED_ON_MAIN=""
    run_stage() {
      commit_files 'chore: gitignore the M5 request log and runtime directory' \
        .gitignore
      commit_files 'build: add the serve extra and move prometheus-client into core' \
        pyproject.toml
      commit_files 'feat(config): resolve config paths from COMPLAINTIQ_ROOT for the container' \
        src/complaintiq/config.py
    }
    ;;
  m5-runtime)
    BRANCH='feat/m5-runtime-metrics'
    # step 5 of the M5 merge order; depends on: 2 (scrub counts, quality check, security), 3 (request log); app.py wires both
    NEED_ON_MAIN="src/complaintiq/serving/security.py src/complaintiq/serving/request_log.py"
    run_stage() {
      commit_files 'feat(monitoring): add Prometheus metrics and request middleware' \
        src/complaintiq/monitoring/metrics.py
      commit_files 'feat(serving): add inference timeout, runtime fallback and env-gated failure hooks' \
        src/complaintiq/serving/runtime.py
      commit_files 'feat(serving): load-time fallback chain, COMPLAINTIQ_PREDICTOR override, no stub in deployment' \
        src/complaintiq/serving/predictor.py
      commit_files 'feat(serving): add optional reason field to the triage response' \
        src/complaintiq/serving/schemas.py
      commit_files 'feat(serving): wire scrub, quality check, guarded inference, audit log, metrics and security' \
        src/complaintiq/serving/app.py
      commit_files 'feat(config): serve the frozen baseline with a 2 s timeout and no stub fallback' \
        configs/serving.yaml \
        configs/model.yaml
      commit_files 'test(serving): select the stub explicitly and expect the reason field' \
        tests/test_api.py \
        tests/test_serving_calibrated.py
      commit_files 'test(serving): cover PII-free logs, quality routing, timeout, fallback, metrics, 429, 413, store down' \
        tests/test_api_runtime.py
    }
    ;;
  m5-ui-deploy)
    BRANCH='feat/m5-ui-deploy-loadtest'
    # step 6 of the M5 merge order; depends on: 5 (runtime, metrics; tests import tests/test_api_runtime.py)
    NEED_ON_MAIN="src/complaintiq/serving/runtime.py tests/test_api_runtime.py"
    run_stage() {
      commit_files 'build: serve the stub explicitly in the dev/CI image' \
        docker/Dockerfile
      commit_files 'build: add the Hugging Face Space image for the frozen model' \
        docker/docker-compose.serve.yml \
        deploy/hf_space/Dockerfile \
        deploy/hf_space/README.md
      commit_files 'feat(ui): add Streamlit reviewer console and its Space image' \
        ui/app.py \
        ui/ciq_client.py \
        ui/.streamlit/config.toml \
        deploy/hf_ui_space/Dockerfile \
        deploy/hf_ui_space/README.md
      commit_files 'feat(scripts): stage the Spaces with model manifest checks' \
        scripts/build_space.py
      commit_files 'feat(scripts): add concurrent load test' \
        scripts/load_test_remote.py
      commit_files 'feat(scripts): add C8 failure tests and the deployment record' \
        scripts/failure_tests.py \
        scripts/deployment_report.py
      commit_files 'test(scripts): cover Space staging, load test, failure scenarios, deployment record and UI client' \
        tests/test_deploy_scripts.py
      commit_files 'ci: run tests, pip-audit and a Space image smoke test' \
        .github/workflows/ci.yml
      commit_files 'build: add M5 Makefile targets' \
        Makefile
      commit_files 'docs: add deployment guide with exact commands' \
        docs/deployment.md
      commit_files 'docs(m5): add load test report and run log' \
        reports/m5/load_test.md \
        reports/m5/results/load_test_local.json \
        reports/m5/results/load_test_public.json \
        reports/experiments/m5/load_test.csv
      commit_files 'docs(m5): add failure test report and run log' \
        reports/m5/failure_tests.md \
        reports/m5/results/failure_tests.json \
        reports/experiments/m5/failure_tests.csv
      commit_files 'docs(m5): add deployment record and model manifest' \
        reports/m5/deployment.md \
        reports/m5/results/deployment_local.json \
        reports/m5/results/deployment_public.json \
        reports/m5/results/model_manifest.json
    }
    ;;
  m5-commit-plan)
    BRANCH='docs/m5-commit-plan'
    # step 7 of the M5 merge order; depends on: 6
    NEED_ON_MAIN="scripts/build_space.py docs/deployment.md"
    run_stage() {
      commit_files 'docs: add M5 commit plan and per-person scripts' \
        docs/COMMIT_PLAN_M5.md \
        scripts/commit_plan_m5/p3.sh \
        scripts/commit_plan_m5/p4.sh
    }
    ;;
  *) die "usage: $0 <stage>   (stages: m5-gitignore-config m5-runtime m5-ui-deploy m5-commit-plan)" ;;
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
if [ "$STAGE" = "m5-ui-deploy" ] && git show "$IMPORT_REF:reports/m5/deployment.md" | grep -q "Public API URL: TODO"; then
  echo
  echo "WARNING: reports/m5/deployment.md on $IMPORT_REF has no public URL yet. If you have deployed,"
  echo "         push the public results to import/m5-files first (docs/deployment.md section 5),"
  echo "         delete this branch (git switch main && git branch -D $BRANCH) and run this stage again."
fi
echo "Next steps:"
echo "  1. Run the tests: make test   (and make lint)"
echo "  2. Push:          git push -u origin $BRANCH"
echo "  3. Open a pull request: $REPO_URL/compare/main...$BRANCH"
echo "     base: main, compare: $BRANCH, title: the first commit message above. Reviewer: Udita."
echo "  4. Merge only when CI is green."
if [ "$STAGE" = "m5-commit-plan" ]; then
  echo "  5. After merge, tag M5:  git switch main && git pull origin main && git tag m5 && git push origin m5"
else
  echo "  5. After merge: git switch main && git pull origin main, then run the next stage in docs/COMMIT_PLAN_M5.md."
fi
