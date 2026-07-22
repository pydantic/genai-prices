# Agentic price-check workflows

Two [gh-aw](https://github.com/github/gh-aw) agentic workflows that compare the
prices recorded in `prices/providers/*.yml` against each provider's **official
pricing page** and file a GitHub issue when they diverge. This complements the
existing aggregator-based checks (`make check-for-price-discrepancies`, which
uses LiteLLM / OpenRouter / etc.) by reading the authoritative source directly.

| Workflow                                  | Providers                | Issue                              |
| ----------------------------------------- | ------------------------ | ---------------------------------- |
| `agentic-price-check-openai-anthropic.md` | OpenAI, Anthropic        | `[price-check/openai-anthropic] …` |
| `agentic-price-check-google-mistral.md`   | Google (Gemini), Mistral | `[price-check/google-mistral] …`   |

Each agent is told the **exact pricing URL** to fetch per provider (it does not
browse the site), reads the recorded `prices:` from the YAML, and compares. When one or
more prices differ it files **one rolling issue** and, via `close-older-issues: true`,
closes the previous one, so at most one discrepancy issue is ever open. When every price
matches (or a page can't be read and nothing else diverges) the agent stays silent: it
files and closes nothing. So after you fix the last flagged price the next run goes quiet
but does **not** auto-close the open issue, so close it yourself, or leave it for the next
discrepancy run to replace.

They run weekly (Mondays) and on manual dispatch, gated on the
`AGENTIC_WORKFLOWS_ENABLED` repo variable, with the engine keyed on the
`FIREWORKS_API_KEY` secret (Claude Code via Fireworks, minimax-m3, matching the
pydantic/platform fleet). To use Anthropic directly instead, edit the `engine:` block in
both `.md` files: set `ANTHROPIC_API_KEY` to the Anthropic secret and remove the
Fireworks-specific bits (`api-target`, `ANTHROPIC_BASE_URL`, and the `ANTHROPIC_MODEL` /
`ANTHROPIC_DEFAULT_*_MODEL` overrides, which pin the model to Fireworks `minimax-m3`) so
runs use a real Anthropic model. Then recompile.

## Editing / extending

These are gh-aw workflows: the `.md` is the source, the `.lock.yml` is compiled
output — **never edit the `.lock.yml` by hand**. After editing a `.md`:

```bash
gh extension install github/gh-aw --pin v0.82.2   # once; the version pin matters, see below
gh aw compile                                     # regenerates the .lock.yml files
```

**Compile with gh-aw v0.82.2 (pinned on purpose).** Newer gh-aw (v0.82.13+) compiles the
api-proxy with token-steering and AI-credits cost accounting that rejects any model it has
no pricing entry for (`HTTP 400 unknown_model_ai_credits`). The Fireworks `minimax-m3`
model isn't in gh-aw's pricing catalog, so a newer compiler makes every run fail before it
fetches a page. v0.82.2 predates that accounting and is the version the pydantic/platform
minimax fleet runs on. Recompiling with a newer version silently reintroduces the failure
until `minimax-m3` is added to gh-aw's pricing table (or a fallback price is configured).

To cover more providers, copy one of the `.md` files, then update **every** piece of
provider-specific text: the `name`, `description`, and `emoji` frontmatter; the
`title-prefix` and `close-older-key`; the `network.allowed` domains; and, in the prompt
body, the per-provider YAML paths, pricing URLs, the Step 3 id-to-page-name matching
examples, and the Step 4 issue title. Then run `gh aw compile`.

## Notes / caveats

- **JS-rendered pages.** `web-fetch` returns page HTML without executing JavaScript, so
  a pure single-page-app pricing page may come back empty. The prompt tells the agent to
  record that provider as unread; it still files any discrepancies it confirmed for the
  _other_ provider, and only stays silent when nothing diverged. If a provider's page is
  unreadable, repoint the workflow at a static **docs** pricing page where one is listed
  under that provider YAML's `pricing_urls:` (not every provider lists an alternative).
- Agents run read-only; issue creation goes through gh-aw safe-outputs, not a
  write token on the agent itself.
