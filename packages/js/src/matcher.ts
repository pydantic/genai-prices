import { Provider, ModelInfo } from './types.js'

function matchLogic(logic: any, text: string): boolean {
  if ('or' in logic) {
    return logic.or.some((clause: any) => matchLogic(clause, text))
  }
  if ('and' in logic) {
    return logic.and.every((clause: any) => matchLogic(clause, text))
  }
  if ('equals' in logic) {
    return text === logic.equals
  }
  if ('starts_with' in logic) {
    return text.startsWith(logic.starts_with)
  }
  if ('ends_with' in logic) {
    return text.endsWith(logic.ends_with)
  }
  if ('contains' in logic) {
    return text.includes(logic.contains)
  }
  if ('regex' in logic) {
    return new RegExp(logic.regex).test(text)
  }
  return false
}

// Provider aliases mapping - maps various provider names to standardized provider IDs
const PROVIDER_ALIASES: Record<string, string> = {
  // Google aliases
  gemini: 'google',
  'google-gla': 'google',
  'google-vertex': 'google',
  'google-ai': 'google',

  // Meta aliases
  'meta-llama': 'meta',
  llama: 'meta',

  // Mistral aliases
  mistralai: 'mistral',

  // Anthropic aliases
  anthropic: 'anthropic',
  claude: 'anthropic',

  // OpenAI aliases
  openai: 'openai',
  gpt: 'openai',

  // Other common aliases
  cohere: 'cohere',
  groq: 'groq',
  fireworks: 'fireworks',
  deepseek: 'deepseek',
  perplexity: 'perplexity',
  together: 'together',
  aws: 'aws',
  azure: 'azure',
  openrouter: 'openrouter',
  novita: 'novita',
  'x-ai': 'x-ai',
  avian: 'avian',
}

/**
 * Normalize a provider name to a standardized provider ID
 * @param providerName - The raw provider name from the system
 * @returns The normalized provider ID
 */
export function normalizeProvider(providerName: string): string {
  const normalized = providerName.toLowerCase().trim()
  return PROVIDER_ALIASES[normalized] || normalized
}

/**
 * Normalize a model name based on provider and model patterns
 * @param providerId - The normalized provider ID
 * @param modelName - The raw model name
 * @returns The normalized model name
 */
export function normalizeModel(providerId: string, modelName: string): string {
  const model = modelName.trim()

  // Anthropic model normalization
  if (providerId === 'anthropic' && model.startsWith('claude-opus-4')) {
    return 'claude-opus-4-20250514'
  }

  // OpenAI model normalization
  if (providerId === 'openai' && model.startsWith('gpt-3.5-turbo')) {
    return 'gpt-3.5-turbo'
  }

  return model
}

export function matchProvider(
  providers: Provider[],
  modelRef: string,
  providerId?: string,
  providerApiUrl?: string,
): Provider | undefined {
  // If providerId is provided, normalize it first
  if (providerId) {
    const normalizedProviderId = normalizeProvider(providerId)
    return providers.find((p) => p.id === normalizedProviderId)
  }
  if (providerApiUrl) {
    return providers.find((p) => new RegExp(p.api_pattern).test(providerApiUrl))
  }
  // Try model_match logic
  return providers.find((p) => p.model_match && matchLogic(p.model_match, modelRef))
}

export function matchModel(models: ModelInfo[], modelRef: string): ModelInfo | undefined {
  return models.find((m) => matchLogic(m.match, modelRef))
}
