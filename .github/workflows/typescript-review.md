---
emoji: '🔷'
name: 'TypeScript Review'
description: 'Advisory TypeScript contract review after CI succeeds on a same-repository pull request head.'
on:
  workflow_run:
    workflows: ['CI']
    types: [completed]
    # workflow_run branches are pull-request head branches. Match every head;
    # deterministic eligibility below decides whether the completed run is safe.
    branches: ['**']
  roles: [admin, maintainer, write]
permissions:
  actions: read
  contents: read
  pull-requests: read
concurrency:
  group: ${{ github.workflow }}-${{ github.event.workflow_run.head_branch }}-${{ github.event.workflow_run.head_sha }}
  cancel-in-progress: false
if: ${{ needs.eligibility.outputs.eligible == 'true' }}
engine:
  id: pydantic-ai
model: copilot/claude-sonnet-4-5
safe-outputs:
  needs: [eligibility]
  footer: false
  activation-comments: false
  report-failure-as-issue: false
  report-failed-jobs: false
  noop:
    report-as-issue: false
  missing-tool: false
  missing-data: false
  report-incomplete: false
  create-pull-request-review-comment:
    max: 30
    target: ${{ needs.eligibility.outputs.pr_number }}
  submit-pull-request-review:
    max: 1
    target: ${{ needs.eligibility.outputs.pr_number }}
    footer: always
    supersede-older-reviews: true
imports:
  - github/gh-aw/.github/workflows/shared/pydantic.md@db25fdfdb4ad50c5b0d10de9977b709401760378
jobs:
  eligibility:
    runs-on: ubuntu-latest
    timeout-minutes: 5
    permissions:
      contents: read
      pull-requests: read
    outputs:
      eligible: ${{ steps.gate.outputs.eligible }}
      reason: ${{ steps.gate.outputs.reason }}
      pr_number: ${{ steps.gate.outputs.pr_number }}
      head_sha: ${{ steps.gate.outputs.head_sha }}
      head_ref: ${{ steps.gate.outputs.head_ref }}
      base_ref: ${{ steps.gate.outputs.base_ref }}
    steps:
      - name: Check out the trusted eligibility policy
        uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd # v6.0.2
        with:
          persist-credentials: false
      - name: Resolve the pull request and decide eligibility
        id: gate
        env:
          GH_TOKEN: ${{ github.token }}
          REPO: ${{ github.repository }}
          RUN_CONCLUSION: ${{ github.event.workflow_run.conclusion }}
          RUN_EVENT: ${{ github.event.workflow_run.event }}
          RUN_HEAD_BRANCH: ${{ github.event.workflow_run.head_branch }}
          RUN_HEAD_REPO: ${{ github.event.workflow_run.head_repository.full_name }}
          RUN_HEAD_SHA: ${{ github.event.workflow_run.head_sha }}
        run: |
          set -euo pipefail

          ASSOCIATED_PRS=$(gh api --paginate --slurp "repos/${REPO}/commits/${RUN_HEAD_SHA}/pulls?per_page=100" | jq 'add')
          MATCHING_PRS=$(printf '%s' "$ASSOCIATED_PRS" | jq \
            --arg branch "$RUN_HEAD_BRANCH" --arg sha "$RUN_HEAD_SHA" \
            '[.[] | select(.state == "open" and .head.ref == $branch and .head.sha == $sha)]')

          if [ "$(printf '%s' "$MATCHING_PRS" | jq 'length')" -eq 1 ]; then
            PR_NUMBER=$(printf '%s' "$MATCHING_PRS" | jq -r '.[0].number')
            RESOLVED_PR=$(gh api "repos/${REPO}/pulls/${PR_NUMBER}")
            CHANGED_FILES=$(gh api --paginate --slurp "repos/${REPO}/pulls/${PR_NUMBER}/files?per_page=100" | jq 'add')
            REVIEWS=$(gh api --paginate --slurp "repos/${REPO}/pulls/${PR_NUMBER}/reviews?per_page=100" | jq 'add')
          else
            RESOLVED_PR=null
            CHANGED_FILES='[]'
            REVIEWS='[]'
          fi

          jq -n \
            --arg ci_conclusion "$RUN_CONCLUSION" \
            --arg event_name "$RUN_EVENT" \
            --arg target_repo "$REPO" \
            --arg head_branch "$RUN_HEAD_BRANCH" \
            --arg head_repo "$RUN_HEAD_REPO" \
            --arg head_sha "$RUN_HEAD_SHA" \
            --argjson matching_prs "$MATCHING_PRS" \
            --argjson resolved_pr "$RESOLVED_PR" \
            --argjson changed_files "$CHANGED_FILES" \
            --argjson reviews "$REVIEWS" \
            '{
              ci_conclusion: $ci_conclusion,
              event_name: $event_name,
              target_repo: $target_repo,
              trigger: {head_branch: $head_branch, head_repo: $head_repo, head_sha: $head_sha},
              matching_prs: $matching_prs,
              resolved_pr: $resolved_pr,
              changed_files: $changed_files,
              reviews: $reviews
            }' \
            | python3 .github/scripts/typescript_review_eligibility.py \
            >> "$GITHUB_OUTPUT"
pre-agent-steps:
  - name: Check out the trusted pull request head
    env:
      BASE_REF: ${{ needs.eligibility.outputs.base_ref }}
      HEAD_REF: ${{ needs.eligibility.outputs.head_ref }}
      HEAD_SHA: ${{ needs.eligibility.outputs.head_sha }}
    run: |
      set -euo pipefail
      git fetch --no-tags origin \
        "+refs/heads/${BASE_REF}:refs/remotes/origin/${BASE_REF}" \
        "+refs/heads/${HEAD_REF}:refs/remotes/origin/${HEAD_REF}"
      git checkout --detach "$HEAD_SHA"
---

Review pull request `${{ needs.eligibility.outputs.pr_number }}` at commit
`${{ needs.eligibility.outputs.head_sha }}`. The eligibility job resolved these values and
checked out that same-repository head. Treat them as authoritative.

Review only the changed TypeScript package contract and its cross-language inputs. Inspect the
complete diff from `origin/${{ needs.eligibility.outputs.base_ref }}` to the checked-out head.
Do not modify files. Do not push commits. Use safe outputs for review comments and the final review.

Check for defects in all of these areas:

- exported API widening or narrowing;
- new `any`, `unknown`, assertions, or suppressions;
- immediate validation of untrusted decoded data;
- separation between wire-format types and internal types;
- Promise and thenable behavior;
- agreement between generated declarations, generated data, and their source inputs;
- JavaScript and Python behavioral parity;
- compile-time type tests and runtime regression tests.

Comment inline only when a concrete defect is anchored to a changed line. Do not report style
preferences or speculative risks. Avoid duplicating the same finding in the final review body.

Submit exactly one formal review. Use `REQUEST_CHANGES` when at least one actionable defect should
block the change. Use `APPROVE` otherwise. Begin the review body with this exact line, followed by a
blank line:

Reviewed at `${{ needs.eligibility.outputs.head_sha }}`.
