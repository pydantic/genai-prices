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

export function matchModel(models: ModelInfo[], modelRef: string): ModelInfo | undefined {
  return models.find((model) => matchLogic(model.match, modelRef))
}

export function matchProvider(
  providers: Provider[],
  modelRef: string,
  providerId?: string,
  providerApiUrl?: string,
): Provider | undefined {
  if (providerId) {
    return providers.find((p) => p.id === providerId)
  }
  if (providerApiUrl) {
    return providers.find((p) => new RegExp(p.apiPattern).test(providerApiUrl))
  }
  // Try model_match logic
  return providers.find((p) => p.modelMatch && matchLogic(p.modelMatch, modelRef))
}
