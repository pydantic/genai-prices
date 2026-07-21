import assert from 'node:assert/strict'
import { performance } from 'node:perf_hooks'
import process from 'node:process'
import { parseArgs } from 'node:util'

import type { ModelPrice, ModelPriceCalculationResult, PriceCalculationResult, Provider, Usage } from '../src/types'

import { calcPrice as calcPricePublic, updatePrices } from '../src/api'
import { calcPrice as calcPriceDirect } from '../src/engine'

const DEFAULT_ITERATIONS = 10_000
const DEFAULT_SAMPLES = 5
const DEFAULT_WARMUP_ITERATIONS = 2_000
const BENCHMARK_TIMESTAMP = new Date('2026-01-01T00:00:00Z')

interface BenchmarkCase {
  expected: ModelPriceCalculationResult
  modelPrice: ModelPrice
  modelRef: string
  name: string
  usage: Usage
}

interface BenchmarkResult {
  caseName: string
  maxNsPerOp: number
  medianNsPerOp: number
  minNsPerOp: number
  pathName: string
}

interface BenchmarkSettings {
  iterations: number
  samples: number
  warmupIterations: number
}

function priceResult(result: PriceCalculationResult): ModelPriceCalculationResult {
  assert.ok(result, 'public price calculation did not find the benchmark fixture')
  return {
    input_price: result.input_price,
    output_price: result.output_price,
    total_price: result.total_price,
  }
}

function assertPriceResult(actual: ModelPriceCalculationResult, expected: ModelPriceCalculationResult, label: string): void {
  for (const field of ['input_price', 'output_price', 'total_price'] as const) {
    const difference = Math.abs(actual[field] - expected[field])
    assert.ok(difference <= Number.EPSILON, `${label} ${field} ${actual[field].toString()} != ${expected[field].toString()}`)
  }
}

function createCases(): BenchmarkCase[] {
  const complexUsage: Usage = {
    cache_audio_read_tokens: 100,
    cache_read_tokens: 400,
    input_audio_tokens: 300,
    input_tokens: 1_000,
    output_audio_tokens: 50,
    output_tokens: 200,
  }
  const complexExpected = {
    input_price: 0.00816,
    output_price: 0.0056,
    total_price: 0.01376,
  }
  const complexBuiltIn = calcPricePublic(complexUsage, 'gpt-realtime', {
    providerId: 'openai',
    timestamp: BENCHMARK_TIMESTAMP,
  })
  assertPriceResult(priceResult(complexBuiltIn), complexExpected, 'complex built-in result changed')
  assert.ok(complexBuiltIn)

  const fixtures: Omit<BenchmarkCase, 'modelRef'>[] = [
    {
      expected: { input_price: 0, output_price: 0, total_price: 0 },
      modelPrice: {},
      name: 'empty',
      usage: {},
    },
    {
      expected: { input_price: 0.002, output_price: 0, total_price: 0.002 },
      modelPrice: { input_mtok: 2 },
      name: 'one-key',
      usage: { input_tokens: 1_000 },
    },
    {
      expected: { input_price: 0.002, output_price: 0.001, total_price: 0.003 },
      modelPrice: { input_mtok: 2, output_mtok: 10 },
      name: 'ordinary-two-key',
      usage: { input_tokens: 1_000, output_tokens: 100 },
    },
    {
      expected: { input_price: 0.001575, output_price: 0, total_price: 0.001575 },
      modelPrice: {
        cache_audio_read_mtok: 0.25,
        cache_read_mtok: 0.5,
        input_audio_mtok: 3,
        input_mtok: 2,
      },
      name: 'four-key-cache-modality-overlap',
      usage: {
        cache_audio_read_tokens: 100,
        cache_read_tokens: 400,
        input_audio_tokens: 300,
        input_tokens: 1_000,
      },
    },
    {
      expected: complexExpected,
      modelPrice: complexBuiltIn.model_price,
      name: 'complex-six-key-built-in',
      usage: complexUsage,
    },
  ]

  return fixtures.map((fixture) => ({ ...fixture, modelRef: `benchmark-${fixture.name}` }))
}

function createBenchmarkProvider(cases: BenchmarkCase[]): Provider {
  return {
    api_pattern: '^benchmark://',
    id: 'benchmark',
    models: cases.map((benchmarkCase) => ({
      id: benchmarkCase.modelRef,
      match: { equals: benchmarkCase.modelRef },
      prices: benchmarkCase.modelPrice,
    })),
    name: 'Local benchmark fixture',
  }
}

function assertExpectedResults(benchmarkCase: BenchmarkCase): void {
  const direct = calcPriceDirect(benchmarkCase.usage, benchmarkCase.modelPrice)
  assertPriceResult(direct, benchmarkCase.expected, `${benchmarkCase.name} direct result changed`)

  const publicCalculation = calcPricePublic(benchmarkCase.usage, benchmarkCase.modelRef, {
    providerId: 'benchmark',
    timestamp: BENCHMARK_TIMESTAMP,
  })
  assertPriceResult(priceResult(publicCalculation), benchmarkCase.expected, `${benchmarkCase.name} public result changed`)
}

function runIterations(operation: () => unknown, iterations: number): void {
  for (let iteration = 0; iteration < iterations; iteration += 1) {
    operation()
  }
}

function measure(
  caseName: string,
  pathName: string,
  operation: () => unknown,
  { iterations, samples, warmupIterations }: BenchmarkSettings
): BenchmarkResult {
  runIterations(operation, warmupIterations)

  const sampleNsPerOp: number[] = []
  for (let sample = 0; sample < samples; sample += 1) {
    const started = performance.now()
    runIterations(operation, iterations)
    const elapsedNs = (performance.now() - started) * 1_000_000
    sampleNsPerOp.push(elapsedNs / iterations)
  }
  sampleNsPerOp.sort((left, right) => left - right)

  const middle = Math.floor(sampleNsPerOp.length / 2)
  const minNsPerOp = sampleNsPerOp[0]
  const maxNsPerOp = sampleNsPerOp.at(-1)
  const upperMiddle = sampleNsPerOp[middle]
  assert.ok(minNsPerOp !== undefined && maxNsPerOp !== undefined && upperMiddle !== undefined)

  let medianNsPerOp = upperMiddle
  if (sampleNsPerOp.length % 2 === 0) {
    const lowerMiddle = sampleNsPerOp[middle - 1]
    assert.ok(lowerMiddle !== undefined)
    medianNsPerOp = (lowerMiddle + upperMiddle) / 2
  }

  return {
    caseName,
    maxNsPerOp,
    medianNsPerOp,
    minNsPerOp,
    pathName,
  }
}

function runBenchmarks(settings: BenchmarkSettings): BenchmarkResult[] {
  const cases = createCases()
  const provider = createBenchmarkProvider(cases)
  updatePrices(({ setProviderData }) => {
    setProviderData([provider])
  })

  for (const benchmarkCase of cases) {
    assertExpectedResults(benchmarkCase)
  }

  const results: BenchmarkResult[] = []
  for (const benchmarkCase of cases) {
    results.push(measure(benchmarkCase.name, 'direct', () => calcPriceDirect(benchmarkCase.usage, benchmarkCase.modelPrice), settings))
    results.push(
      measure(
        benchmarkCase.name,
        'public',
        () =>
          calcPricePublic(benchmarkCase.usage, benchmarkCase.modelRef, {
            providerId: 'benchmark',
            timestamp: BENCHMARK_TIMESTAMP,
          }),
        settings
      )
    )
  }
  return results
}

function positiveInt(value: string, option: string): number {
  const parsed = Number(value)
  if (!Number.isSafeInteger(parsed) || parsed < 1) {
    throw new Error(`${option} must be a positive integer`)
  }
  return parsed
}

function parseSettings(): BenchmarkSettings {
  const { values } = parseArgs({
    options: {
      iterations: { default: String(DEFAULT_ITERATIONS), type: 'string' },
      samples: { default: String(DEFAULT_SAMPLES), type: 'string' },
      'warmup-iterations': { default: String(DEFAULT_WARMUP_ITERATIONS), type: 'string' },
    },
  })

  return {
    iterations: positiveInt(values.iterations, '--iterations'),
    samples: positiveInt(values.samples, '--samples'),
    warmupIterations: positiveInt(values['warmup-iterations'], '--warmup-iterations'),
  }
}

function main(): void {
  const settings = parseSettings()
  const results = runBenchmarks(settings)

  console.log(`Node ${process.version} (V8 ${process.versions.v8})`)
  console.log(
    `iterations=${settings.iterations.toString()} samples=${settings.samples.toString()} warmup_iterations=${settings.warmupIterations.toString()}`
  )
  console.log('case                                      path      median ns/op      min ns/op      max ns/op')
  for (const result of results) {
    console.log(
      `${result.caseName.padEnd(41)} ${result.pathName.padEnd(7)} ${result.medianNsPerOp.toFixed(1).padStart(13)} ${result.minNsPerOp.toFixed(1).padStart(14)} ${result.maxNsPerOp.toFixed(1).padStart(14)}`
    )
  }
}

main()
