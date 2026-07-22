# Agentic price-check workflows

Two [gh-aw](https://github.com/github/gh-aw) agentic workflows that compare the
prices recorded in `prices/providers/*.yml` against each provider's **official
pricing page** and file a GitHub issue when they diverge. This complements the
existing aggregator-based checks (`make check-for-price-discrepancies`, which
uses LiteLLM / OpenRouter / etc.) by reading the authoritative source directly.

| Workflow | Providers | Issue |
|---|---|---|
| `agentic-price-check-openai-anthropic.md` | OpenAI, Anthropic | `[price-check/openai-anthropic] …` |
| `agentic-price-check-google-mistral.md` | Google (Gemini), Mistral | `[price-check/google-mistral] …` |

Each agent is told the **exact pricing URL** to fetch per provider (it does not
browse the site), reads the recorded `prices:` from the YAML, and compares. It
files **one rolling issue** per run with `close-older-issues: true`, so the open
issue always reflects the current state: fix a price in the YAML and the next run
drops it; a provider raises a price and it reappears. No duplicate issues, no
manual closing. If nothing diverges (or a page can't be read) the agent no-ops.

## Enabling (maintainer, one time)

1. **Add the LLM secret.** The engine is Claude Code via Fireworks (matching the
   pydantic/platform fleet). Add a repo secret `FIREWORKS_API_KEY`. To use
   Anthropic directly instead, edit the `engine:` block in both `.md` files to
   `ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}` (drop the
   `ANTHROPIC_BASE_URL` / `api-target` lines) and recompile.
2. **Turn them on.** Set repo variable `AGENTIC_WORKFLOWS_ENABLED` to `true`
   (the workflows are gated on it, so they stay dormant until you do). Run:
   `gh variable set AGENTIC_WORKFLOWS_ENABLED --body true`.
3. Trigger a manual run to smoke-test: the **Actions** tab → each workflow →
   *Run workflow*, or `gh workflow run agentic-price-check-openai-anthropic.lock.yml`.

They otherwise run weekly (Mondays).

## Editing / extending

These are gh-aw workflows: the `.md` is the source, the `.lock.yml` is compiled
output — **never edit the `.lock.yml` by hand**. After editing a `.md`:

```bash
gh extension install github/gh-aw   # once
gh aw compile                       # regenerates the .lock.yml files
```

To cover more providers, copy one of the `.md` files, change the `name`,
`title-prefix`, `close-older-key`, the `network.allowed` domains, and the
per-provider YAML paths + pricing URLs in the prompt, then `gh aw compile`.

## Notes / caveats

- **JS-rendered pages.** `web-fetch` returns page HTML without executing
  JavaScript, so a pure single-page-app pricing page may come back empty. The
  prompt tells the agent to say so and no-op rather than guess. If a provider's
  page is unreadable, point the workflow at its static **docs** pricing page
  instead (several are listed under `pricing_urls:` in each provider YAML).
- Agents run read-only; issue creation goes through gh-aw safe-outputs, not a
  write token on the agent itself.
