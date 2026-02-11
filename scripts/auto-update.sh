#!/bin/bash
#
# Fetch latest prices, detect aliases, apply, build, and optionally open a PR.
#
# Usage:
#   ./auto-update.sh           # fetch, detect, apply, format, build — review the diff
#   ./auto-update.sh --pr      # same, then commit, push, and open a PR
#

set -e

# ── Refuse to run on a dirty tree ────────────────────────────────────
if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "Error: working tree has uncommitted changes. Commit or stash them first."
  exit 1
fi

# ── Full pipeline: fetch, detect, apply, format, build ───────────────
REPORT_JSON=$(mktemp)
PR_BODY=$(mktemp)
trap 'rm -f "$REPORT_JSON" "$PR_BODY"' EXIT

echo "==> Fetching source prices..."
uv run -m prices get_openrouter_prices
uv run -m prices get_litellm_prices
uv run -m prices get_simonw_prices

echo "==> Detecting and applying aliases..."
uv run python -c "
import json
from prices.auto_update import detect_auto_updates, apply_auto_updates
report = detect_auto_updates()
with open('$REPORT_JSON', 'w') as f:
    json.dump(report.to_dict(), f, indent=2)
if not report.applied:
    print('No aliases to apply.')
    raise SystemExit(0)
print(f'Found {len(report.applied)} alias(es), applying...')
saved = apply_auto_updates(report)
print(f'Applied to {len(saved)} provider(s).')
"

# Exit early if nothing was applied
n_applied=$(jq '.applied | length' "$REPORT_JSON")
if [ "$n_applied" -eq 0 ]; then
  echo "Nothing to do."
  exit 0
fi

# ── Generate PR body markdown from report JSON ────────────────────────
echo "==> Generating PR body..."
{
  echo "## Auto-Update Price Aliases"
  echo ""
  echo "### Auto-Applied Aliases"
  echo ""
  echo "| Provider | New Alias | Mapped To | Price Match | Name Prefix | Sources |"
  echo "|----------|-----------|-----------|:-----------:|:-----------:|---------|"
  jq -r '.applied[] | "| \(.provider_id) | `\(.new_alias)` | `\(.existing_model_id)` | \(.match_type) | yes | \(.source_names | join(", ")) |"' "$REPORT_JSON"

  n_unresolved=$(jq '.unresolved | length' "$REPORT_JSON")
  if [ "$n_unresolved" -gt 0 ]; then
    echo ""
    echo "### Unrecognized Models (require review)"
    echo ""
    jq -r '.unresolved | group_by(.provider_id) | .[] | "**\(.[0].provider_id)**\n\([ .[] | "- `\(.model_id)` (\(.source_names | join(", ")))" ] | join("\n"))\n"' "$REPORT_JSON"
  fi
} > "$PR_BODY"

# ── Format + build (mirrors pre-commit hooks so commit is clean) ─────
echo "==> Formatting and building..."
uv run ruff format
uv run ruff check --fix --fix-only
uv sync --frozen --all-packages --all-extras
npm install
make collapse-models
make build
uv run -m prices inject_providers
npx prettier --write --ignore-unknown prices/providers/ packages/

if [ "$1" != "--pr" ]; then
  echo "Done."
  exit 0
fi

# ── Commit, push, and open PR ────────────────────────────────────────
echo "==> Creating PR..."
git checkout -B auto-update/prices main
git add prices/providers/ prices/data.json prices/data_slim.json packages/
git add prices/data.schema.json prices/data_slim.schema.json
git commit -m "feat: auto-update price aliases"
git push -u origin auto-update/prices --force-with-lease
gh pr create \
  --title "feat: auto-update price aliases" \
  --body-file "$PR_BODY"
