# AGENTS.md

Cross-harness agent instructions for this repo. Project setup, architecture, and data-editing rules
live in `CLAUDE.md`.

## After opening or updating a PR

Don't go idle until the PR is genuinely in its desired end state. After pushing, poll (~every 30s)
until **both**:

- CI is green, and
- every reviewer comment (cubic included) is addressed or explicitly dismissed.

A PR with unresolved review threads is not mergeable. Resolve each one — fix and reply, or dismiss
with a reason — except threads left intentionally as informational (not meant to be resolved).
