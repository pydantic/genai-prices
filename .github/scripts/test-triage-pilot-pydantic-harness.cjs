'use strict'

const assert = require('node:assert/strict')
const { cpSync, mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } = require('node:fs')
const { tmpdir } = require('node:os')
const { join } = require('node:path')
const { spawnSync } = require('node:child_process')

const actionsDir = process.env.GH_AW_ACTIONS_DIR
assert(actionsDir, 'GH_AW_ACTIONS_DIR is required')

const workflowPath = '.github/workflows/genai-prices-triage-pilot.lock.yml'
const workflow = readFileSync(workflowPath, 'utf8')
const harness = workflow.match(
  /cat <<'GHAW_HARNESS_SCRIPT_3c7b9f1a_EOF' > "\$\{RUNNER_TEMP\}\/gh-aw\/actions\/pydantic-ai_harness\.cjs"\n(?<script>[\s\S]*?)\n          GHAW_HARNESS_SCRIPT_3c7b9f1a_EOF/,
)
assert(harness?.groups?.script, 'could not extract the generated Pydantic AI harness')
const harnessScript = harness.groups.script.replace(/^ {10}/gm, '')
assert.match(harnessScript, /^const \{ spawnSync \} = require\("child_process"\);$/m)
assert.match(harnessScript, /^const AGENT_MODULE = `from pathlib import Path$/m)

const expectedSetupPin = '30aadb1626371455f145991c6385924babda2d04'
const ciWorkflow = readFileSync('.github/workflows/ci.yml', 'utf8')
assert.match(ciWorkflow, new RegExp(`uses: github/gh-aw-actions/setup@${expectedSetupPin} # v0\\.86\\.3`))
const setupPins = new Set(
  [...workflow.matchAll(/uses: github\/gh-aw-actions\/setup@([0-9a-f]{40})/g)].map((match) => match[1]),
)
assert.deepEqual(setupPins, new Set([expectedSetupPin]))

const testDir = mkdtempSync(join(tmpdir(), 'triage-pilot-pydantic-harness-'))
try {
  const runnerTemp = join(testDir, 'runner-temp')
  const helperDir = join(runnerTemp, 'gh-aw', 'actions')
  const homeDir = join(testDir, 'home')
  const pythonBin = join(testDir, 'python', 'bin')
  const workspace = join(testDir, 'workspace')
  const prompt = join(testDir, 'prompt.txt')
  const output = join(testDir, 'pai-base-url.txt')
  const preload = join(testDir, 'reflect-stub.cjs')
  const hostAliases = join(testDir, 'hostaliases')

  cpSync(actionsDir, helperDir, { recursive: true })
  mkdirSync(join(homeDir, '.local', 'bin'), { recursive: true })
  mkdirSync(pythonBin, { recursive: true })
  mkdirSync(workspace, { recursive: true })
  writeFileSync(join(helperDir, 'pydantic-ai_harness.cjs'), harnessScript)
  writeFileSync(prompt, 'triage the issue')
  // The helper reads this sandbox alias to select the host-side api-proxy bridge.
  writeFileSync(hostAliases, 'api-proxy 127.0.0.1\n')
  writeFileSync(join(pythonBin, 'python3'), '#!/bin/sh\nexit 0\n', { mode: 0o755 })
  writeFileSync(
    join(homeDir, '.local', 'bin', 'pai'),
    '#!/bin/sh\nprintf \'%s\' "$OPENAI_BASE_URL" > "$PAI_OUTPUT"\n',
    { mode: 0o755 },
  )
  writeFileSync(
    preload,
    `global.fetch = async url => {
  if (url !== "http://api-proxy:10000/reflect") throw new Error(\`unexpected reflection URL: \${url}\`);
  return {
    ok: true,
    json: async () => ({
      endpoints: [{ configured: true, provider: "copilot", port: 10002, models: [], models_url: "http://api-proxy:10002/v1/models" }],
    }),
  };
};
`,
  )

  const result = spawnSync(
    process.execPath,
    ['--require', preload, join(helperDir, 'pydantic-ai_harness.cjs'), 'pai'],
    {
      cwd: workspace,
      encoding: 'utf8',
      env: {
        ...process.env,
        AWF_REFLECT_ENABLED: '1',
        GH_AW_LLM_PROVIDER: 'github',
        GH_AW_PROMPT: prompt,
        GITHUB_WORKSPACE: workspace,
        GH_AW_API_PROXY_HOST_BRIDGE: 'host.docker.internal',
        HOME: homeDir,
        HOSTALIASES: hostAliases,
        PAI_MODEL: 'copilot/claude-sonnet-4-5',
        PAI_OUTPUT: output,
        RUNNER_TEMP: runnerTemp,
        pythonLocation: join(testDir, 'python'),
      },
    },
  )

  assert.equal(result.status, 0, result.stderr || result.stdout)
  assert.equal(readFileSync(output, 'utf8'), 'http://host.docker.internal:10002/v1')
} finally {
  rmSync(testDir, { force: true, recursive: true })
}
