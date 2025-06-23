import { providers } from "./cost/providers/mappings.ts";
import type { ModelRow } from "./cost/interfaces/Cost.ts";
import { resolve } from "node:path";

/// we don't include tiered pricing here because helicone won't need that format
export interface ModelPrice {
  input_mtok?: number;
  input_audio_mtok?: number;
  cache_write_mtok?: number;
  cache_read_mtok?: number;
  output_mtok?: number;
  output_audio_mtok?: number;
}

type ProvidePrices = Record<string, ModelPrice>;
type SourcePrices = Record<string, ProvidePrices>;

function mapPrice(cost: ModelRow): ModelPrice {
  /// prices including undefined values
  const pricesAll = {
    input_mtok: toMtok(cost.cost.prompt_token),
    input_audio_mtok: toMtok(cost.cost.prompt_audio_token),
    cache_write_mtok: toMtok(cost.cost.prompt_cache_write_token),
    cache_read_mtok: toMtok(cost.cost.prompt_cache_read_token),
    output_mtok: toMtok(cost.cost.completion_token),
    output_audio_mtok: toMtok(cost.cost.completion_audio_token),
  };
  return Object.fromEntries(
    Object.entries(pricesAll).filter(([, v]) => v !== undefined),
  );
}

// round to 6 decimal places
const round = (p: number) => Math.round(p * 1_000_000) / 1_000_000;
// multiply by 1 million since we use mtok
const toMtok = (p?: number) => p ? round(p * 1_000_000) : undefined;

function providerPrices(costs: ModelRow[]): ProvidePrices {
  const prices: ProvidePrices = {};

  for (const cost of costs) {
    prices[cost.model.value] = mapPrice(cost);
  }

  return prices;
}

if (import.meta.main) {
  const sourcePrices: SourcePrices = {};

  for (const { provider, costs } of providers) {
    // ignore openrouter, the prices are wrong and we have data directly from openrouter
    if (costs && provider !== "OPENROUTER") {
      const prices = providerPrices(costs);
      const providerId = provider.toLowerCase();
      sourcePrices[providerId] = prices;
      console.log(`${providerId}: ${Object.keys(prices).length} prices found`);
    }
  }
  const writePath = `${import.meta.dirname}/../source_prices/helicone.json`;
  await Deno.writeTextFile(writePath, JSON.stringify(sourcePrices, null, 2));
  console.log("prices written to", resolve(writePath));
}
