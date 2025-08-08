/* eslint-disable @typescript-eslint/no-non-null-assertion */
import { Provider, Usage, UsageExtractor } from './types.js'

export function extractUsage(provider: Provider, responseData: unknown, apiFlavor?: string): [string, Usage] {
  if (!provider.extractors) {
    throw new Error('No extraction logic defined for this provider')
  }
  let extractor: UsageExtractor

  if (!apiFlavor) {
    if (provider.extractors.length === 1) {
      extractor = provider.extractors[0]!
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
      const currentValue = usage[mapping.dest] ?? 0
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
  data: Record<string, unknown>,
  typeCheck: TypeCheck<T>,
  required: true,
  dataPath: string[]
): T
// eslint-disable-next-line no-redeclare
function extractPath<T>(
  path: string | string[],
  data: Record<string, unknown>,
  typeCheck: TypeCheck<T>,
  required: boolean,
  dataPath: string[]
): null | T
// eslint-disable-next-line no-redeclare
function extractPath<T>(
  path: string | string[],
  data: Record<string, unknown>,
  typeCheck: TypeCheck<T>,
  required: boolean,
  dataPath: string[]
): null | T {
  const [last, ...steps] = asArray(path).reverse()
  if (typeof last !== 'string') {
    throw new Error(`Expected last step of path to be a string, got ${typeName(last)}`)
  }

  let currentStepData: Record<string, unknown> = data
  steps.reverse()

  const errorPath: string[] = []

  for (const step of steps) {
    errorPath.push(step)
    currentStepData = currentStepData[step] as Record<string, unknown>
    const dataType = typeName(currentStepData)
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

  const value = currentStepData[last]
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
    throw new Error(`Expected \`${[...dataPath, ...errorPath].join('.')}\` value to be a ${typeCheck.name}, got ${typeName(value)}`)
  }
}

function asArray(v: string | string[]): string[] {
  // return a shallow copy of the array, otherwise the reverse calls above modify our data in-place.
  return Array.isArray(v) ? [...v] : [v]
}

function typeName(v: unknown): string {
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
  guard(value: unknown): value is T
  name: string
}

const mappingCheck: TypeCheck<Record<string, unknown>> = {
  guard: (value: unknown): value is Record<string, unknown> => typeName(value) === 'mapping',
  name: 'mapping',
}

const stringCheck: TypeCheck<string> = {
  guard: (value: unknown): value is string => typeof value === 'string',
  name: 'string',
}

const numberCheck: TypeCheck<number> = {
  guard: (value: unknown): value is number => typeof value === 'number',
  name: 'number',
}
