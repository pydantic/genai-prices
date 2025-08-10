import { Provider, Usage, UsageExtractor } from './types.js'

export function extractUsage(provider: Provider, responseData: any, apiFlavor?: string): [string, Usage] {
  if (!provider.extractors) {
    throw new Error('No extraction logic defined for this provider')
  }
  let extractor: UsageExtractor

  if (!apiFlavor) {
    if (provider.extractors.length === 1) {
      extractor = provider.extractors[0]
    } else {
      throw new Error('No apiFlavor specified and multiple extractors available')
    }
  } else {
    const foundExtractor = provider.extractors.find((e) => e.api_flavor === apiFlavor)
    if (foundExtractor) {
      extractor = foundExtractor
    } else {
      const availableFlavors = provider.extractors.map((e) => e.api_flavor).join(', ')
      throw new Error(`Unknown apiFlavor '${apiFlavor}', allowed values: ${availableFlavors}`)
    }
  }

  if (!mappingCheck.guard(responseData)) {
    throw new Error(`Expected response data to be a mapping object, got ${typeName(responseData)}`)
  }

  const modelName = extractPath(extractor.model_path, responseData, stringCheck, true, [])

  const root = asArray(extractor.root)
  const usageObj = extractPath(root, responseData, mappingCheck, true, [])

  const usage: Usage = {}

  for (const mapping of extractor.mappings) {
    const value = extractPath(mapping.path, usageObj, numberCheck, mapping.required, root)
    if (value !== null) {
      const currentValue = usage[mapping.dest] || 0
      usage[mapping.dest] = currentValue + value
    }
  }

  if (!Object.keys(usage).length) {
    throw new Error(`No usage information found at ${JSON.stringify(extractor.root)}`)
  }

  return [modelName, usage]
}

function extractPath<T>(
  path: string | string[],
  data: Record<string, any>,
  typeCheck: TypeCheck<T>,
  required: true,
  dataPath: string[],
): T
function extractPath<T>(
  path: string | string[],
  data: Record<string, any>,
  typeCheck: TypeCheck<T>,
  required: boolean,
  dataPath: string[],
): T | null
function extractPath<T>(
  path: string | string[],
  data: Record<string, any>,
  typeCheck: TypeCheck<T>,
  required: boolean,
  dataPath: string[],
): T | null {
  const [last, ...steps] = asArray(path).reverse()
  steps.reverse()

  const errorPath: string[] = []

  for (const step of steps) {
    errorPath.push(step)
    data = data[step]
    const dataType = typeName(data)
    if (dataType === 'undefined') {
      if (required) {
        throw new Error(`Missing value at \`${[...dataPath, ...errorPath].join('.')}\``)
      } else {
        return null
      }
    } else if (dataType !== 'mapping') {
      throw new Error(`Expected \`${[...dataPath, ...errorPath].join('.')}\` value to be a mapping, got ${dataType}`)
    }
  }

  const value = data[last]
  if (typeof value === 'undefined') {
    if (required) {
      errorPath.push(last)
      throw new Error(`Missing value at \`${[...dataPath, ...errorPath].join('.')}\``)
    } else {
      return null
    }
  }

  if (typeCheck.guard(value)) {
    return value
  } else {
    errorPath.push(last)
    throw new Error(
      `Expected \`${[...dataPath, ...errorPath].join('.')}\` value to be a ${typeCheck.name}, got ${typeName(value)}`,
    )
  }
}

const asArray = (v: string | string[]): string[] => (Array.isArray(v) ? v : [v])

function typeName(v: any): string {
  if (v === null) {
    return 'null'
  } else if (Array.isArray(v)) {
    return 'array'
  } else if (typeof v === 'object') {
    return 'mapping'
  } else {
    return typeof v
  }
}

interface TypeCheck<T> {
  guard(value: any): value is T
  name: string
}

const mappingCheck: TypeCheck<Record<string, any>> = {
  guard: (value: any): value is Record<string, any> => typeName(value) === 'mapping',
  name: 'mapping',
}

const stringCheck: TypeCheck<string> = {
  guard: (value: any): value is string => typeof value === 'string',
  name: 'string',
}

const numberCheck: TypeCheck<number> = {
  guard: (value: any): value is number => typeof value === 'number',
  name: 'number',
}
