import { Usage, ModelPrice, TieredPrices, ModelInfo, ConditionalPrice } from './types.js';

function calcTieredPrice(tiered: TieredPrices, tokens: number): number {
  if (tokens <= 0) return 0;
  let price = 0;
  // Sort tiers by start ascending
  const tiers = [...tiered.tiers].sort((a, b) => a.start - b.start);

  // Base price for tokens up to the first tier start
  const firstTierStart = tiers[0]?.start ?? tokens;
  const baseTokens = Math.min(tokens, firstTierStart);
  price += (baseTokens * tiered.base) / 1_000_000;

  // Price for each tier
  for (let i = 0; i < tiers.length; i++) {
    const tier = tiers[i];
    const nextTierStart = tiers[i + 1]?.start ?? Infinity;
    // Tokens in this tier: from tier.start up to nextTierStart or tokens
    const tierTokenCount = Math.max(0, Math.min(tokens, nextTierStart) - tier.start);
    if (tierTokenCount > 0) {
      price += (tierTokenCount * tier.price) / 1_000_000;
    }
  }

  return price;
}

function calcMtokPrice(
  field: number | TieredPrices | undefined,
  tokens: number | undefined,
  label?: string
): number {
  if (!field || !tokens || tokens <= 0) return 0;
  if (typeof field === 'number') {
    return (field * tokens) / 1_000_000;
  } else {
    return calcTieredPrice(field, tokens);
  }
}

export function calcPrice(usage: Usage, modelPrice: ModelPrice): number {
  let price = 0;
  price += calcMtokPrice(modelPrice.inputMtok, usage.inputTokens, 'inputMtok');
  price += calcMtokPrice(modelPrice.cacheWriteMtok, usage.cacheWriteTokens, 'cacheWriteMtok');
  price += calcMtokPrice(modelPrice.cacheReadMtok, usage.cacheReadTokens, 'cacheReadMtok');
  price += calcMtokPrice(modelPrice.outputMtok, usage.outputTokens, 'outputMtok');
  price += calcMtokPrice(modelPrice.inputAudioMtok, usage.inputAudioTokens, 'inputAudioMtok');
  price += calcMtokPrice(
    modelPrice.cacheAudioReadMtok,
    usage.cacheAudioReadTokens,
    'cacheAudioReadMtok'
  );
  price += calcMtokPrice(modelPrice.outputAudioMtok, usage.outputAudioTokens, 'outputAudioMtok');
  if (modelPrice.requestsKcount !== undefined) {
    price += modelPrice.requestsKcount * ((usage.requests ?? 1) / 1000);
  }
  return price;
}

export function getActiveModelPrice(model: ModelInfo, timestamp: Date): ModelPrice {
  if (!Array.isArray(model.prices)) {
    return model.prices;
  }
  // Conditional prices: last active wins
  for (let i = model.prices.length - 1; i >= 0; i--) {
    const cond = model.prices[i] as ConditionalPrice;
    if (!cond.constraint) return cond.prices;
    if (cond.constraint.type === 'start_date') {
      if (timestamp >= new Date(cond.constraint.startDate)) {
        return cond.prices;
      }
    } else if (cond.constraint.type === 'time_of_date') {
      const t = timestamp.toTimeString().slice(0, 8);
      if (t >= cond.constraint.startTime && t < cond.constraint.endTime) {
        return cond.prices;
      }
    }
  }
  // Fallback to first
  return (model.prices[0] as ConditionalPrice).prices;
}
