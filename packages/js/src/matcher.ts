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
  // If providerId is provided, try to find by provider_match logic
  if (providerId) {
    const normalizedProviderId = providerId.toLowerCase().trim()

    // First try exact match by ID
    const exactMatch = providers.find((p) => p.id === normalizedProviderId)
    if (exactMatch) return exactMatch

    // Then try provider_match logic
    const provider = providers.find((p) => p.provider_match && matchLogic(p.provider_match, normalizedProviderId))
    if (provider) return provider

    // If providerId is provided but not found, return undefined (don't fall back to model matching)
    return undefined
  }

  if (providerApiUrl) {
    return providers.find((p) => new RegExp(p.api_pattern).test(providerApiUrl))
  }
  // Try model_match logic only if no providerId was provided
  return providers.find((p) => p.model_match && matchLogic(p.model_match, modelRef))
}

export function matchModel(models: ModelInfo[], modelRef: string): ModelInfo | undefined {
  return models.find((m) => matchLogic(m.match, modelRef))
}
