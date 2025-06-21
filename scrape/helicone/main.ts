import { stringify } from "jsr:@std/yaml";
import { providers } from "./cost/providers/mappings.ts";
import type { ProviderName } from "./cost/providers/mappings.ts";
import type {
  ModelDetails,
  ModelDetailsMap,
  ModelRow,
} from "./cost/interfaces/Cost.ts";

export interface Provider {
  name: string;
  id: string;
  pricing_url?: string;
  api_pattern?: string;
  description?: string;
  models: ModelInfo[];
}

export interface ModelInfo {
  name: string;
  description?: string;
  id: string;
  matches: LogicClause;
  max_tokens?: number;
  prices: ModelPrice; // | ConditionalPrice[];
}

export interface ModelPrice {
  input_mtok?: number | TieredPrices;
  input_audio_mtok?: number | TieredPrices;
  cache_write_mtok?: number | TieredPrices;
  cache_read_mtok?: number | TieredPrices;
  output_mtok?: number | TieredPrices;
  output_audio_mtok?: number | TieredPrices;
}

export interface TieredPrices {
  base: number;
  tiers: Tier[];
}

export interface Tier {
  start: number;
  price: number;
}

export interface ConditionalPrice {
  constraint?: StartDateConstraint;
  prices: ModelPrice;
}

export interface StartDateConstraint {
  start: string; // ISO date string
}

export interface ClauseStartsWith {
  starts_with: string;
}

export interface ClauseEndsWith {
  ends_with: string;
}

export interface ClauseContains {
  contains: string;
}

export interface ClauseRegex {
  regex: string;
  any?: string[];
}

export interface ClauseEquals {
  equals: string;
}

export interface ClauseOr {
  or: LogicClause[];
}

export interface ClauseAnd {
  and: LogicClause[];
}

export type LogicClause =
  | ClauseStartsWith
  | ClauseEndsWith
  | ClauseContains
  | ClauseRegex
  | ClauseEquals
  | ClauseOr
  | ClauseAnd;

function mapProvider(
  pattern: RegExp,
  provider: ProviderName,
  costs?: ModelRow[],
  modelDetails?: ModelDetailsMap,
): Provider | undefined {
  if (provider === "NEBIUS") {
    console.warn("NEBIUS provider is not supported, it has weird pricing");
    return;
  }
  if (!costs) {
    console.warn(`No costs found for provider ${provider}`);
    return;
  }
  console.log("Processing provider", provider);

  const models: ModelInfo[] = [];
  for (const cost of costs) {
    const model = mapModel(cost, modelDetails);
    const matchingModel = models.find((m) =>
      m.id === model.id &&
      m.max_tokens === model.max_tokens
    );
    if (matchingModel) {
      const pricesMatch = pricesEqual(matchingModel.prices, model.prices);
      if (pricesMatch) {
        if ("or" in matchingModel.matches) {
          matchingModel.matches.or.push(model.matches);
        } else {
          const copy = { ...matchingModel.matches };
          matchingModel.matches = { or: [copy, model.matches] };
        }
        continue;
      }
      console.warn(
        `Prices do not match for model ${model.id}`,
        matchingModel.prices,
        model.prices,
      );
    }
    models.push(model);
  }
  return {
    name: provider.toLowerCase(),
    id: provider.toLowerCase(),
    api_pattern: pattern.toString().replaceAll(/\\\//g, "/").replace(
      /^\/\^/,
      "",
    ),
    models: costs.map((c) => mapModel(c, modelDetails)).filter((m) => !!m),
  };
}

function mapModel(
  cost: ModelRow,
  modelDetails?: ModelDetailsMap,
): ModelInfo {
  const details = findDetails(
    cost.model,
    modelDetails,
  );
  const pricesUndefined = {
    input_mtok: toMtok(cost.cost.prompt_token),
    input_audio_mtok: toMtok(cost.cost.prompt_audio_token),
    cache_write_mtok: toMtok(cost.cost.prompt_cache_write_token),
    cache_read_mtok: toMtok(cost.cost.prompt_cache_read_token),
    output_mtok: toMtok(cost.cost.completion_token),
    output_audio_mtok: toMtok(cost.cost.completion_audio_token),
  };
  const prices = Object.fromEntries(
    Object.entries(pricesUndefined).filter(([, v]) => v !== undefined),
  );
  const matches = mapMatches(cost.model);
  if (!details) {
    return {
      name: cost.model.value,
      id: cost.model.value,
      matches,
      prices,
    };
  }
  return {
    name: details.searchTerms[0],
    description: details.info.description,
    id: cost.model.value,
    matches,
    max_tokens: details.info.maxTokens,
    prices,
  };
}

// round to 6 decimal places
const round = (p: number) => Math.round(p * 1_000_000) / 1_000_000;
// multiply by 1 million since we use mtok
const toMtok = (p?: number) => p ? round(p * 1_000_000) : undefined;

function findDetails(
  { operator, value }: {
    operator: "equals" | "startsWith" | "includes";
    value: string;
  },
  modelDetails?: ModelDetailsMap,
): ModelDetails | undefined {
  if (!modelDetails) return;
  for (const details of Object.values(modelDetails)) {
    if (operator === "equals" && details.matches.includes(value)) {
      return details;
    } else if (
      operator === "startsWith" &&
      details.matches.find((match) => match.startsWith(value))
    ) {
      return details;
    } else if (
      operator === "includes" &&
      details.matches.find((match) => match.includes(value))
    ) {
      return details;
    }
  }
}

function mapMatches(
  { operator, value }: {
    operator: "equals" | "startsWith" | "includes";
    value: string;
  },
): LogicClause {
  switch (operator) {
    case "equals":
      return { equals: value };
    case "startsWith":
      return { starts_with: value };
    case "includes":
      return { contains: value };
  }
}

function pricesEqual(p1: ModelPrice, p2: ModelPrice): boolean {
  if (Object.keys(p1).length !== Object.keys(p2).length) {
    return false;
  }
  for (const [key, value] of Object.entries(p1)) {
    // deno-lint-ignore no-explicit-any
    if (value !== (p2 as any)[key]) {
      return false;
    }
  }
  return true;
}

if (import.meta.main) {
  for (const { pattern, provider, costs, modelDetails } of providers) {
    const pydanticProvider = mapProvider(
      pattern,
      provider,
      costs,
      modelDetails,
    );
    if (pydanticProvider) {
      // console.log(pydanticProvider);
      await Deno.writeTextFile(
        `providers/${pydanticProvider.id}.yml`,
        stringify(pydanticProvider),
      );
      // break;
    }
  }
}
