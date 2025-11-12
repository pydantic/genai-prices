import { matchLogic } from './engine'
import { ArrayMatch, ExtractPath, Provider, Usage } from './types'

interface ExtractedUsage {
  model: null | string
  usage: Usage
}

export function extractUsage(provider: Provider, responseData: unknown, apiFlavor?: string): ExtractedUsage {
  apiFlavor = apiFlavor ?? 'default'

  if (!provider.extractors) {
    throw new Error('No extraction logic defined for this provider')
  }

  const extractor = provider.extractors.find((e) => e.api_flavor === apiFlavor)
  if (!extractor) {
    const availableFlavors = provider.extractors.map((e) => e.api_flavor).join(', ')
    throw new Error(`Unknown apiFlavor '${apiFlavor}', allowed values: ${availableFlavors}`)
  }

  if (!mappingCheck.guard(responseData)) {
    throw new Error(`Expected response data to be a mapping object, got ${typeName(responseData)}`)
  }

  const model = extractPath(extractor.model_path, responseData, stringCheck, false, [])

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

  return { model, usage }
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
      } else if (!required) {
        return null
      } else {
        throw new Error(`Expected \`${dottedPath(dataPath, errorPath)}\` value to be a mapping, got ${typeName(currentStepData)}`)
      }
    } else {
      if (mappingCheck.guard(currentStepData)) {
        currentStepData = currentStepData[step]
      } else if (!required) {
        return null
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
    if (required) {
      throw new Error(`Expected \`${dottedPath(dataPath, errorPath)}\` value to be a mapping, got ${typeName(currentStepData)}`)
    } else {
      return null
    }
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
  } else if (required) {
    errorPath.push(last)
    throw new Error(`Expected \`${dottedPath(dataPath, errorPath)}\` value to be a ${typeCheck.name}, got ${typeName(value)}`)
  } else {
    return null
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
