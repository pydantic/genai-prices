/* eslint-disable @typescript-eslint/no-non-null-assertion */
import { matchLogic } from './engine'
import { ArrayMatch, ExtractPath, Provider, Usage, UsageExtractor } from './types'

export function extractUsage(provider: Provider, responseData: unknown, apiFlavor?: string, modelName?: string): [string, Usage] {
  console.log('provider', provider)
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

  modelName = modelName ?? extractPath(extractor.model_path, responseData, stringCheck, true, [])

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

function extractPath<T>(path: ExtractPath, data: unknown, typeCheck: TypeCheck<T>, required: true, dataPath: (ArrayMatch | string)[]): T
// eslint-disable-next-line no-redeclare
function extractPath<T>(
  path: ExtractPath,
  data: unknown,
  typeCheck: TypeCheck<T>,
  required: boolean,
  dataPath: (ArrayMatch | string)[]
): null | T
// eslint-disable-next-line no-redeclare
function extractPath<T>(
  path: ExtractPath,
  data: unknown,
  typeCheck: TypeCheck<T>,
  required: boolean,
  dataPath: (ArrayMatch | string)[]
): null | T {
  const [last, ...steps] = asArray(path).reverse()
  if (typeof last !== 'string') {
    throw new Error(`Expected last step of path to be a string, got ${typeName(last)}`)
  }
  steps.reverse()

  let currentStepData = data
  const errorPath: (ArrayMatch | string)[] = []

  for (const step of steps) {
    errorPath.push(step)
    if (typeof step === 'object') {
      if (Array.isArray(currentStepData)) {
        currentStepData = extractArrayMatch(step, currentStepData)
      } else {
        throw new Error(`Expected \`${dottedPath(dataPath, errorPath)}\` value to be a mapping, got ${typeName(currentStepData)}`)
      }
    } else {
      if (mappingCheck.guard(currentStepData)) {
        currentStepData = currentStepData[step]
      } else {
        throw new Error(`Expected \`${dottedPath(dataPath, errorPath)}\` value to be a mapping, got ${typeName(currentStepData)}`)
      }
    }

    if (typeof currentStepData === 'undefined') {
      if (required) {
        const msg = typeof step === 'object' ? 'Unable to find item' : 'Missing value'
        throw new Error(`${msg} at \`${dottedPath(dataPath, errorPath)}\``)
      } else {
        return null
      }
    }
  }

  if (!mappingCheck.guard(currentStepData)) {
    throw new Error(`Expected \`${dottedPath(dataPath, errorPath)}\` value to be a mapping, got ${typeName(currentStepData)}`)
  }

  const value = currentStepData[last]
  if (typeof value === 'undefined') {
    if (required) {
      errorPath.push(last)
      throw new Error(`Missing value at \`${dottedPath(dataPath, errorPath)}\``)
    } else {
      return null
    }
  }

  if (typeCheck.guard(value)) {
    return value
  } else {
    errorPath.push(last)
    throw new Error(`Expected \`${dottedPath(dataPath, errorPath)}\` value to be a ${typeCheck.name}, got ${typeName(value)}`)
  }
}

function extractArrayMatch(finder: ArrayMatch, items: unknown[]): Record<string, unknown> | undefined {
  for (const item of items) {
    if (mappingCheck.guard(item)) {
      const itemField = item[finder.field]
      if (typeof itemField === 'string' && matchLogic(finder.match, itemField)) {
        return item
      }
    }
  }
}

function asArray(v: ExtractPath): (ArrayMatch | string)[] {
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

const dottedPath = (dataPath: (ArrayMatch | string)[], errorPath: (ArrayMatch | string)[]): string =>
  [...dataPath.map(asString), ...errorPath.map(asString)].join('.')

const asString = (v: ArrayMatch | string): string => (typeof v === 'string' ? v : JSON.stringify(v))
