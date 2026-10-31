import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

function runCli(...args: string[]) {
  const result = spawnSync(process.execPath, ['--import', 'tsx', fileURLToPath(new URL('../cli.ts', import.meta.url)), ...args], {
    cwd: fileURLToPath(new URL('../../', import.meta.url)),
    encoding: 'utf8',
    timeout: 10_000,
  })
  expect(result.error).toBeUndefined()
  return result
}

function priceContextOptions(pairs: string[]): string[] {
  return pairs.flatMap((pair) => ['--price-context', pair])
}

describe('--price-context', () => {
  it.each([
    [[], '$10'],
    [['service_tier=flex'], '$5'],
    [['processing=batch'], '$5'],
    // `region` selects no variant, so each case costs $5 only if the `service_tier` pair, first or last, reaches the calculation.
    [['service_tier=flex', 'region=eu'], '$5'],
    [['region=eu', 'service_tier=flex'], '$5'],
    [['region=eu,service_tier=flex'], '$5'],
    [[' service_tier=flex , region=eu '], '$5'],
  ])('prices openai:o3 with %j', (pairs, totalPrice) => {
    const result = runCli(
      'calc',
      '--input-tokens',
      '1000000',
      '--output-tokens',
      '1000000',
      '--timestamp',
      '2026-10-14T00:00:00Z',
      ...priceContextOptions(pairs),
      'openai:o3'
    )
    expect(result.stderr).toBe('')
    expect(result.status).toBe(0)
    expect(result.stdout).toContain(`   Total Price: ${totalPrice}\n`)
  })

  it('treats inherited object property names as ordinary keys', () => {
    const result = runCli('calc', '--input-tokens', '1000', ...priceContextOptions(['__proto__=x', 'constructor=y']), 'o3')
    expect(result.stderr).toBe('')
    expect(result.status).toBe(0)
  })

  it.each([
    [['bogus'], "Error: Invalid --price-context 'bogus', expected key=value\n"],
    [['=flex'], "Error: Invalid --price-context '=flex', expected key=value\n"],
    [['service_tier='], "Error: Invalid --price-context 'service_tier=', expected key=value\n"],
    [['service_tier=flex', 'service_tier=priority'], "Error: Duplicate --price-context 'service_tier', it was already set to 'flex'\n"],
    [['service_tier=flex, service_tier=priority'], "Error: Duplicate --price-context 'service_tier', it was already set to 'flex'\n"],
    [['__proto__=x', '__proto__=y'], "Error: Duplicate --price-context '__proto__', it was already set to 'x'\n"],
  ])('rejects %j', (pairs, error) => {
    const result = runCli('calc', '--input-tokens', '1000', ...priceContextOptions(pairs), 'o3')
    expect(result.status).toBe(1)
    expect(result.stdout).toBe('')
    expect(result.stderr).toBe(error)
  })
})
