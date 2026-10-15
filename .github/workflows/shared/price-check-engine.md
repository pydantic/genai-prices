---
# gh-aw resolves imported engine configuration after loading the public definition.
# Keep provider credentials in this routing configuration; AWF excludes the key
# from the sandbox and injects it upstream in the API proxy.
engine:
  id: pydantic-ai
  version: '0.56.0'
  env:
    PAI_AGENT: scripts.price_check_agent:agent
    ANTHROPIC_BASE_URL: https://api.z.ai/api/anthropic
    ANTHROPIC_API_KEY: ${{ secrets.ZAI_API_KEY }}
# gh-aw exports canonical usage from the host. Exclude exporter variables from
# the tool container, including Linux ancestor-process environments.
excluded-env:
  - GH_AW_OTLP_ENDPOINTS
  - OTEL_EXPORTER_OTLP_ENDPOINT
  - OTEL_EXPORTER_OTLP_HEADERS
---
