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
  prices: ModelPrice | ConditionalPrice[];
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
  }
  if (!costs) {
    console.warn(`No costs found for provider ${provider}`);
  } else if (!modelDetails) {
    console.warn(`No model details found for provider ${provider}`);
  } else {
    return {
      name: provider,
      id: provider,
      api_pattern: pattern.toString(),
      models: costs.map((c) => mapModel(c, modelDetails)).filter((m) => !!m),
    };
  }
}

function mapModel(
  cost: ModelRow,
  modelDetails: ModelDetailsMap,
): ModelInfo | undefined {
  const details = findDetails(
    cost.model,
    modelDetails,
  );
  if (!details) {
    console.warn(`No model details found for ${cost.model}`);
    return;
  }
  return {
    name: details.searchTerms[0],
    description: details.info.description,
    id: details.matches[0],
    matches: mapMatches(cost.model),
    max_tokens: details.info.maxTokens,
    prices: {
      input_mtok: cost.cost.prompt_token,
      input_audio_mtok: cost.cost.prompt_audio_token,
      cache_write_mtok: cost.cost.prompt_cache_write_token,
      cache_read_mtok: cost.cost.prompt_cache_read_token,
      output_mtok: cost.cost.completion_token,
      output_audio_mtok: cost.cost.completion_audio_token,
    },
  };
}

function findDetails(
  { operator, value }: {
    operator: "equals" | "startsWith" | "includes";
    value: string;
  },
  modelDetails: ModelDetailsMap,
): ModelDetails | undefined {
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

if (import.meta.main) {
  for (const { pattern, provider, costs, modelDetails } of providers) {
    const pydanticProvider = mapProvider(
      pattern,
      provider,
      costs,
      modelDetails,
    );
    if (pydanticProvider) {
      await Deno.writeTextFile(
        `providers/${provider}.yml`,
        stringify(pydanticProvider),
      );
    }
  }
}
