# Pricing performance benchmarks

The repository includes lightweight, non-gating benchmarks for pricing-call overhead. Run them from the repository root:

```bash
uv run --package genai-prices python benchmarks/python/pricing.py
npm run benchmark:pricing --workspace=packages/js
```

Both commands print the Python or Node runtime version, iteration and sample counts, and the median, minimum, and maximum
nanoseconds per operation. They accept `--iterations`, `--samples`, and `--warmup-iterations` options when a different run
length is useful.

Each runtime measures two paths separately:

- `direct` calls the low-level price calculation with an already selected price.
- `public` calls the package API, including provider/model matching and price calculation.

Both paths use the same deterministic local fixtures and cover five price shapes: empty, one-key input, ordinary two-key
input/output, four-key cache/audio overlap, and a complex six-key price loaded from the bundled data. Fixture construction,
provider setup, imports, and exact result checks happen before timing. Each case and path is warmed up before multiple timed
samples are collected.

Results are directional. Compare revisions only by running the unchanged harness with identical options on the same machine
and runtime/tool versions. Save the raw output locally, labelled by revision, for example:

```bash
benchmark_output_dir="ignoreme/generated/$(date +%F)"
mkdir -p "$benchmark_output_dir"

uv run --package genai-prices python benchmarks/python/pricing.py \
  | tee "$benchmark_output_dir/python-$(git rev-parse --short HEAD).txt"
npm run benchmark:pricing --workspace=packages/js \
  | tee "$benchmark_output_dir/javascript-$(git rev-parse --short HEAD).txt"
```

Repeat those commands on each revision being compared. Do not commit the raw output, quote machine-specific timings as
project-wide performance claims, compare results from different environments, or add timing thresholds to CI.
