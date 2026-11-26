import { format } from 'node:util'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { version } from '../../package.json'
import { calcPrice } from '../index'

class CliExit extends Error {
  readonly code: null | number | string | undefined

  constructor(code: null | number | string | undefined) {
    super(`process.exit(${String(code)})`)
    this.code = code
  }
}

// Runs the CLI in-process, as `genai-prices <args>` would, so coverage sees it.
async function runCli(...args: string[]) {
  const stdout: string[] = []
  const stderr: string[] = []
  vi.spyOn(console, 'log').mockImplementation((...line: unknown[]) => {
    stdout.push(format(...line))
  })
  vi.spyOn(console, 'error').mockImplementation((...line: unknown[]) => {
    stderr.push(format(...line))
  })
  vi.spyOn(process, 'exit').mockImplementation((code) => {
    throw new CliExit(code)
  })
  const argv = process.argv
  process.argv = ['node', 'genai-prices', ...args]
  vi.resetModules()
  try {
    const outcome: unknown = await import('../cli').then(
      () => undefined,
      (error: unknown) => error
    )
    if (!(outcome instanceof CliExit)) throw new Error('CLI finished without calling process.exit')
    return { code: outcome.code, stderr: stderr.join('\n'), stdout: stdout.join('\n') }
  } finally {
    process.argv = argv
  }
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('genai-prices CLI', () => {
  it('prices several models with every usage flag', async () => {
    const timestamp = '2025-06-01T00:00:00Z'
    const usage = {
      cache_audio_read_tokens: 20,
      cache_read_tokens: 200,
      cache_write_tokens: 100,
      input_audio_tokens: 50,
      input_tokens: 1000,
      output_audio_tokens: 30,
      output_tokens: 100,
    }
    const { code, stderr, stdout } = await runCli(
      'calc',
      'openai:gpt-4o',
      'anthropic:claude-v1',
      '--input-tokens=1000',
      '--cache-write-tokens=100',
      '--cache-read-tokens=200',
      '--output-tokens=100',
      '--input-audio-tokens=50',
      '--cache-audio-read-tokens=20',
      '--output-audio-tokens=30',
      `--timestamp=${timestamp}`
    )

    expect({ code, stderr }).toEqual({ code: 0, stderr: '' })
    const [gpt4o, claudeV1] = stdout.split('\n\n')
    const gpt4oPrice = calcPrice(usage, 'gpt-4o', { providerId: 'openai', timestamp: new Date(timestamp) })
    expect(gpt4o).toContain('      Provider: OpenAI\n')
    expect(gpt4o).toMatch(/^Context Window: \d/m)
    expect(gpt4o).toContain(`   Total Price: $${String(gpt4oPrice?.total_price)}\n`)
    // claude-v1 has no display name and no context window in the data.
    expect(claudeV1).toContain('         Model: claude-v1\n')
    expect(claudeV1).not.toContain('Context Window')
  })

  it('prices a bare model name without the calc command', async () => {
    const { code, stdout } = await runCli('gpt-4o', '--input-tokens', '1000')

    expect(code).toBe(0)
    expect(stdout).toContain('      Provider: OpenAI\n')
    expect(stdout).toContain(`   Total Price: $${String(calcPrice({ input_tokens: 1000 }, 'gpt-4o')?.total_price)}\n`)
  })

  it('reports every model it cannot price and exits non-zero', async () => {
    const { code, stderr, stdout } = await runCli('calc', 'not-a-model-anyone-sells', 'openai:gpt-4o', '--input-tokens=abc')

    expect(code).toBe(1)
    expect(stdout).toBe('')
    expect(stderr).toBe(
      [
        'No price found for model not-a-model-anyone-sells',
        'Error for model openai:gpt-4o: Invalid usage value for input_tokens: expected a finite non-negative number',
      ].join('\n')
    )
  })

  it('lists one provider, or all of them', async () => {
    const positional = await runCli('list', 'anthropic')
    const option = await runCli('list', '--provider', 'anthropic')
    const all = await runCli('list')

    expect(option).toEqual(positional)
    expect(positional.code).toBe(0)
    expect(positional.stdout).toMatch(/^Anthropic: \(\d+ models\)\n/)
    expect(positional.stdout).toMatch(/^ {2}anthropic:claude-v1$/m)
    expect(positional.stdout).toMatch(/^ {2}anthropic:claude-[\w.-]+: Claude .+$/m)
    expect(positional.stdout).not.toContain('OpenAI')
    expect(all.code).toBe(0)
    expect(all.stdout).toContain(positional.stdout)
    expect(all.stdout).toMatch(/^OpenAI: \(\d+ models\)$/m)
    expect(await runCli('list', 'nope')).toEqual({ code: 1, stderr: 'Provider nope not found.', stdout: '' })
  })

  it('answers --version and --help, and prints help on misuse', async () => {
    const help = await runCli('--help')

    expect(await runCli('-v')).toEqual({ code: 0, stderr: '', stdout: version })
    expect(help.code).toBe(0)
    expect(help.stdout).toMatch(/^genai-prices <command>\n/)
    expect(await runCli()).toEqual({ ...help, code: 1 })
    const misuse = await runCli('--bogus')
    expect(misuse).toMatchObject({ code: 1, stdout: help.stdout })
    expect(misuse.stderr).toContain("'--bogus'")
  })
})
