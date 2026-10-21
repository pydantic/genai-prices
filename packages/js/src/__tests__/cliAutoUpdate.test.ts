import type { Socket } from 'node:net'

import { execFile, spawn } from 'node:child_process'
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises'
import { createServer } from 'node:http'
import { createRequire } from 'node:module'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { promisify } from 'node:util'
import { describe, expect, it } from 'vitest'

import { version } from '../../package.json'
import { REMOTE_DATA_JSON_URL } from '../api'

const packageDir = fileURLToPath(new URL('../..', import.meta.url))
const tokens = ['--input-tokens', '1000000', '--output-tokens', '1000000']
const catalog = [
  {
    api_pattern: '.*',
    id: 'openai',
    model_match: { starts_with: 'gpt-' },
    models: [
      {
        id: 'gpt-cli-refresh-regression',
        match: { equals: 'gpt-cli-refresh-regression' },
        name: 'Remote only',
        prices: { input_mtok: 3, output_mtok: 5 },
      },
      {
        id: 'gpt-4',
        match: { equals: 'gpt-4' },
        prices: { input_mtok: 7, output_mtok: 11 },
      },
    ],
    name: 'Updated fixture',
  },
]

type Scenario = 'body-error' | 'http-error' | 'invalid-json' | 'network-error' | 'success'

interface Request {
  hasSignal: boolean
  url: string
}

// Each invocation gets a native Node preload and an isolated filesystem fixture.
// Only fetch is controlled; argument parsing, activation and calculation are real.
async function runCli(args: string[], payload: unknown = catalog, scenario: Scenario = 'success') {
  const directory = await mkdtemp(join(tmpdir(), 'genai-cli-update-'))
  const preload = join(directory, 'fetch.mjs')
  const requestsFile = join(directory, 'requests.jsonl')
  await writeFile(requestsFile, '')
  await writeFile(
    preload,
    `import { appendFileSync } from 'node:fs'
import { setTimeout as delay } from 'node:timers/promises'
const payload = ${JSON.stringify(payload)}
const scenario = ${JSON.stringify(scenario)}
globalThis.fetch = async (url, options) => {
  appendFileSync(${JSON.stringify(requestsFile)}, JSON.stringify({
    hasSignal: options?.signal instanceof AbortSignal,
    url: String(url),
  }) + '\\n')
  await delay(30)
  if (scenario === 'network-error') throw new Error('fixture network failure')
  if (scenario === 'http-error') return new Response('unavailable', { status: 503 })
  if (scenario === 'invalid-json') return new Response('{broken')
  return {
    ok: true,
    json: async () => {
      await delay(30)
      if (scenario === 'body-error') throw new Error('fixture body failure')
      return payload
    },
  }
}
`
  )
  try {
    const result = await new Promise<{ code: null | number; stderr: string; stdout: string }>((resolve, reject) => {
      const child = spawn(process.execPath, ['--import', preload, '--import', 'tsx', 'src/cli.ts', ...args], {
        cwd: packageDir,
        env: { LANG: 'C', NO_COLOR: '1', PATH: dirname(process.execPath), TMPDIR: tmpdir(), TZ: 'UTC' },
        timeout: 15_000,
      })
      let stdout = ''
      let stderr = ''
      child.stdout.on('data', (chunk: Buffer) => {
        stdout += chunk.toString()
      })
      child.stderr.on('data', (chunk: Buffer) => {
        stderr += chunk.toString()
      })
      child.on('error', reject)
      child.on('close', (code) => {
        resolve({ code, stderr, stdout })
      })
    })
    const requests = (await readFile(requestsFile, 'utf8'))
      .trim()
      .split('\n')
      .filter(Boolean)
      .map((line) => JSON.parse(line) as Request)
    return { ...result, requests }
  } finally {
    await rm(directory, { force: true, recursive: true })
  }
}

function expectOneFetch(requests: Request[]) {
  expect(requests).toEqual([{ hasSignal: true, url: REMOTE_DATA_JSON_URL }])
}

async function runNativeBodyTimeout() {
  // Always rebuild: source execution and stale bundles can miss the native Node 22 body hang.
  const require = createRequire(import.meta.url)
  const viteCli = join(dirname(require.resolve('vite/package.json')), 'bin/vite.js')
  await promisify(execFile)(process.execPath, [viteCli, 'build', '--config', 'vite.config-cli.ts'], { cwd: packageDir })

  const directory = await mkdtemp(join(tmpdir(), 'genai-cli-native-timeout-'))
  const preload = join(directory, 'fetch.mjs')
  const requestsFile = join(directory, 'requests.jsonl')
  const sockets = new Set<Socket>()
  const serverRequests: (string | undefined)[] = []
  const server = createServer((request, response) => {
    serverRequests.push(request.url)
    response.writeHead(200, { 'content-type': 'application/json' })
    response.write('[')
    // Keep the native HTTP body open past the single download deadline.
  })
  server.on('connection', (socket) => {
    sockets.add(socket)
    socket.on('close', () => sockets.delete(socket))
  })
  try {
    await new Promise<void>((resolve, reject) => {
      server.once('error', reject)
      server.listen(0, '127.0.0.1', resolve)
    })
    const address = server.address()
    if (address === null || typeof address === 'string') throw new Error('Expected a loopback server address')
    await writeFile(requestsFile, '')
    await writeFile(
      preload,
      `import { appendFileSync } from 'node:fs'
const nativeFetch = globalThis.fetch
globalThis.fetch = (url, options) => {
  if (String(url) !== ${JSON.stringify(REMOTE_DATA_JSON_URL)}) throw new Error('Unexpected fetch URL')
  appendFileSync(${JSON.stringify(requestsFile)}, JSON.stringify({
    hasSignal: options?.signal instanceof AbortSignal,
    url: String(url),
  }) + '\\n')
  return nativeFetch(${JSON.stringify(`http://127.0.0.1:${String(address.port)}/catalog`)}, { ...options, redirect: 'error' })
}
`
    )
    const start = performance.now()
    const result = await new Promise<{
      code: null | number
      signal: null | string
      stderr: string
      stdout: string
    }>((resolve, reject) => {
      const child = spawn(process.execPath, ['--import', preload, 'dist/cli.js', 'calc', 'openai:gpt-4', '--auto-update', ...tokens], {
        cwd: packageDir,
        env: { LANG: 'C', NO_COLOR: '1', PATH: dirname(process.execPath), TMPDIR: tmpdir(), TZ: 'UTC' },
        // Failure cleanup only: a harness kill must fail the regression assertions.
        timeout: 15_000,
      })
      let stdout = ''
      let stderr = ''
      child.stdout.on('data', (chunk: Buffer) => {
        stdout += chunk.toString()
      })
      child.stderr.on('data', (chunk: Buffer) => {
        stderr += chunk.toString()
      })
      child.on('error', reject)
      child.on('close', (code, signal) => {
        resolve({ code, signal, stderr, stdout })
      })
    })
    const requests = (await readFile(requestsFile, 'utf8'))
      .trim()
      .split('\n')
      .filter(Boolean)
      .map((line) => JSON.parse(line) as Request)
    return { ...result, elapsed: performance.now() - start, requests, serverRequests }
  } finally {
    for (const socket of sockets) socket.destroy()
    try {
      if (server.listening) {
        await new Promise<void>((resolve, reject) => {
          server.close((error) => {
            if (error) reject(error)
            else resolve()
          })
        })
      }
    } finally {
      await rm(directory, { force: true, recursive: true })
    }
  }
}

describe('CLI --auto-update', () => {
  it.each([
    ['calc', 'openai:gpt-cli-refresh-regression', '--auto-update'],
    ['--auto-update', 'openai:gpt-cli-refresh-regression'],
    ['calc', '--auto-update', 'openai:gpt-cli-refresh-regression', 'openai:gpt-4'],
  ])('waits for a single refresh before quoting %j', async (...args) => {
    const result = await runCli([...args, ...tokens])
    expect(result.code).toBe(0)
    expect(result.stderr).toBe('')
    expect(result.stdout).toContain('Total Price: $8\n')
    if (args.includes('openai:gpt-4')) expect(result.stdout).toContain('Total Price: $18\n')
    expectOneFetch(result.requests)
  })

  it.each([
    ['list', '--auto-update'],
    ['--auto-update', 'list', 'openai'],
    ['list', '--provider', 'openai', '--auto-update'],
  ])('lists the refreshed catalog for %j', async (...args) => {
    const result = await runCli(args)
    expect(result.code).toBe(0)
    expect(result.stderr).toBe('')
    expect(result.stdout).toBe('Updated fixture: (2 models)\n  openai:gpt-cli-refresh-regression: Remote only\n  openai:gpt-4\n')
    expectOneFetch(result.requests)
  })

  it.each([{ start_date: '2025-01-01' }, { end_time: '16:00:00Z', start_time: '08:00:00Z' }])(
    'activates downloaded wire constraints %j before calculation',
    async (constraint) => {
      const payload = [
        {
          ...catalog[0],
          models: [
            {
              id: 'gpt-4',
              match: { equals: 'gpt-4' },
              prices: [{ prices: { input_mtok: 1, output_mtok: 1 } }, { constraint, prices: { input_mtok: 3, output_mtok: 5 } }],
            },
          ],
        },
      ]
      const result = await runCli(['calc', 'openai:gpt-4', '--auto-update', '--timestamp', '2025-01-02T12:00:00Z', ...tokens], payload)
      expect(result.code).toBe(0)
      expect(result.stderr).toBe('')
      expect(result.stdout).toContain('Total Price: $8\n')
      expectOneFetch(result.requests)
    }
  )

  it.each<[string, unknown, Scenario, string]>([
    ['network', catalog, 'network-error', 'fixture network failure'],
    ['HTTP', catalog, 'http-error', '503'],
    ['JSON', catalog, 'invalid-json', 'JSON'],
    ['body', catalog, 'body-error', 'fixture body failure'],
    ['null', null, 'success', 'Expected a provider array'],
    ['object', {}, 'success', 'Expected a provider array'],
    ['activation', [{ ...catalog[0], models: [{ id: 'gpt-4', prices: [{ constraint: {}, prices: {} }] }] }], 'success', 'constraint'],
  ])('fails without a stale quote or listing on %s failure', async (_label, payload, scenario, message) => {
    for (const args of [
      ['calc', 'openai:gpt-4', ...tokens],
      ['list', 'openai'],
    ]) {
      const result = await runCli([...args, '--auto-update'], payload, scenario)
      expect(result.code).toBe(1)
      expect(result.stdout).toBe('')
      expect(result.stderr).toContain('Failed to update prices:')
      expect(result.stderr).toContain(message)
      expect(result.stderr).not.toContain('\n    at ')
      expectOneFetch(result.requests)
    }
  })

  it('reports a bounded timeout while reading a native HTTP body in the fresh CLI bundle', async () => {
    const result = await runNativeBodyTimeout()
    expect(result.signal, JSON.stringify(result)).toBeNull()
    expect(result.code).toBe(1)
    expect(result.stdout).toBe('')
    expect(result.stderr).toContain('Failed to update prices:')
    expect(result.stderr).toMatch(/timeout/i)
    expect(result.stderr).not.toContain('\n    at ')
    expect(result.elapsed).toBeGreaterThanOrEqual(9900)
    expect(result.elapsed).toBeLessThan(14_000)
    expect(result.serverRequests).toEqual(['/catalog'])
    expectOneFetch(result.requests)
  }, 30_000)

  it('treats an empty catalog as fresh and does not fall back to bundled models', async () => {
    const list = await runCli(['list', '--auto-update'], [])
    expect(list.code).toBe(0)
    expect(list.stdout).toBe('')
    expect(list.stderr).toBe('')
    expectOneFetch(list.requests)
    const calc = await runCli(['calc', 'openai:gpt-4', '--auto-update', ...tokens], [])
    expect(calc.code).toBe(1)
    expect(calc.stdout).toBe('')
    expect(calc.stderr).toBe('No price found for model openai:gpt-4\n')
    expectOneFetch(calc.requests)
  })

  it('reports an unknown model and provider against the refreshed catalog', async () => {
    const calc = await runCli(['calc', 'openai:missing', '--auto-update', ...tokens])
    expect(calc.code).toBe(1)
    expect(calc.stdout).toBe('')
    expect(calc.stderr).toBe('No price found for model openai:missing\n')
    expectOneFetch(calc.requests)
    const list = await runCli(['list', 'missing', '--auto-update'])
    expect(list.code).toBe(1)
    expect(list.stdout).toBe('')
    expect(list.stderr).toBe('Provider missing not found.\n')
    expectOneFetch(list.requests)
  })

  it.each([
    { args: ['--auto-update', '--help'], code: 0, output: 'genai-prices <command>' },
    { args: ['--version', '--auto-update'], code: 0, output: version },
    { args: ['--auto-update', '--invalid'], code: 1, output: 'genai-prices <command>' },
    { args: ['calc', '--auto-update'], code: 1, output: 'genai-prices <command>' },
    { args: ['--auto-update'], code: 1, output: 'genai-prices <command>' },
  ])('does not fetch for non-actionable arguments $args', async ({ args, code, output }) => {
    const result = await runCli(args, catalog, 'network-error')
    expect(result.code).toBe(code)
    expect(result.stdout).toContain(output)
    expect(result.requests).toEqual([])
  })

  it('keeps default calculations and listings offline', async () => {
    const calc = await runCli(['calc', 'openai:gpt-4', ...tokens], catalog, 'network-error')
    expect(calc.code).toBe(0)
    expect(calc.stderr).toBe('')
    expect(calc.stdout).toContain('Total Price: $90\n')
    expect(calc.requests).toEqual([])
    const list = await runCli(['list', 'openai'], catalog, 'network-error')
    expect(list.code).toBe(0)
    expect(list.stderr).toBe('')
    expect(list.stdout).toContain('OpenAI: (')
    expect(list.stdout).not.toContain('Remote only')
    expect(list.requests).toEqual([])
  })
})
