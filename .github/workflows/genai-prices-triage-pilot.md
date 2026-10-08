---
name: Triage pilot (pydantic-ai engine)
on:
  issues:
    types: [opened, reopened]
  workflow_dispatch:
  roles: all
if: ${{ vars.AGENTIC_WORKFLOWS_ENABLED == 'true' }}
permissions:
  contents: read
  issues: read
  # Threat detection runs on the built-in copilot engine, which authenticates with this.
  copilot-requests: write
# Strict mode rejects any secret in engine.env. ANTHROPIC_API_KEY reaches only the AWF
# api-proxy: `awf --exclude-env` keeps it out of the agent sandbox.
strict: false
# glm-5.3-flash is not in gh-aw's AI-credit pricing catalog, so the api-proxy would reject
# it while the credit guardrail is on.
max-ai-credits: -1
max-daily-ai-credits: -1
engine:
  id: pydantic-ai
  # The anthropic/ backend sends Messages API requests through the api-proxy, which
  # forwards them to Z.AI's Anthropic-compatible endpoint named by ANTHROPIC_BASE_URL.
  model: anthropic/glm-5.3-flash
  env:
    ANTHROPIC_BASE_URL: https://api.z.ai/api/anthropic
    ANTHROPIC_API_KEY: ${{ secrets.ZAI_API_KEY }}
# The imported engine requires gh-aw v0.91.1 or newer. Compile this workflow alone
# (`gh aw compile genai-prices-triage-pilot`); the price checks stay on v0.82.2.
imports:
  - pydantic/pydantic-ai/src/pydantic_ai_harness/gh-aw/pydantic.md@main
network:
  allowed:
    - defaults
    - api.z.ai
sandbox:
  agent:
    id: awf
timeout-minutes: 20
safe-outputs:
  staged: true
  add-comment:
    max: 1
  add-labels:
  close-issue:
---

# Triage one issue

Triage exactly one open issue in ${{ github.repository }} and record one decision.

## Which issue

- When the run was triggered by an issue event, triage issue #${{ github.event.issue.number }}.
- When the run was triggered manually, triage the newest open issue that has no labels. When every open issue has labels, triage the newest open issue.

## How to decide

Read the issue title, body, and comments. Read the parts of the repository the issue names. Search open and closed issues for duplicates before any other classification.

Pick exactly one decision:

- **duplicate** — an earlier issue reports the same defect or request. Name the canonical issue number.
- **needs-info** — the issue cannot be acted on without facts only the author has. Name each missing fact.
- **actionable** — the issue describes work a maintainer could start now. Name the files a fix would touch.
- **question** — the issue asks how to use the project rather than reporting a defect or requesting a change.
- **not-planned** — the issue asks for something the project has rejected or that contradicts its documented contract. Cite the source of the rejection.
- **needs-maintainer** — the decision requires a judgment call this charter does not cover. Name the open question.

Ground every claim in something you read this run: a file path, an issue number, or a quoted line. Do not decide from the title alone.

## Record the decision

1. Post one comment on the issue with: the decision, a rationale of at most six sentences, and each supporting reference.
2. Apply the repository's existing labels that match the decision. Read the label list first; do not invent new label names.
3. For **duplicate**: close the issue as a duplicate of the canonical issue.
4. For **not-planned**: close the issue as not planned.

The run is complete when the comment is posted and the labels are applied. Do not push code, do not open pull requests, and do not comment on any other issue.
