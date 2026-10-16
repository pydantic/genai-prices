'use strict'

const fs = require('node:fs')
const path = require('node:path')

const BRIDGE_BASE = 'https://team.pydantic.work/api/webhooks/price-check'
const AUDIENCE = BRIDGE_BASE
const REPORT_NAME = 'model-check-report.json'
const MAX_REPORT_BYTES = 32 * 1024
const MAX_BACKFILL_REQUESTS = 10
const MAX_BACKFILL_OUTPUT_BYTES = 64 * 1024
const UUID_PATTERN = /^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/i
const PROVIDER_ID_PATTERN = /^[a-z0-9][a-z0-9_-]*$/
const PR_URL_PATTERN = /^https:\/\/github\.com\/pydantic\/genai-prices\/pull\/[1-9][0-9]*$/

function invalid(message) {
  return new Error(message)
}

function requestId(value) {
  if (typeof value !== 'string' || !UUID_PATTERN.test(value)) throw invalid('Invalid price-check request ID')
  return value
}

function safeText(value, maximum, message) {
  if (
    typeof value !== 'string' ||
    value.length > maximum ||
    value.trim().length === 0 ||
    /[\u0000-\u001f\u007f]/.test(value)
  )
    throw invalid(message)
  return value
}

function sourceURL(value) {
  if (typeof value !== 'string' || value.length > 2048 || /[\u0000-\u0020\u007f]/.test(value))
    throw invalid('Invalid official source URL')
  let url
  try {
    url = new URL(value)
  } catch {
    throw invalid('Invalid official source URL')
  }
  if (url.protocol !== 'https:' || !url.hostname || url.username || url.password || (url.port && url.port !== '443'))
    throw invalid('Invalid official source URL')
  return value
}

function eventRequestId(context) {
  return requestId(context?.payload?.client_payload?.request_id)
}

function knownProviderIds() {
  const providerDirectory = path.join(__dirname, '..', 'prices', 'providers')
  const providerIds = new Set()
  let entries
  try {
    entries = fs.readdirSync(providerDirectory, { withFileTypes: true })
  } catch {
    throw invalid('Trusted provider sources are unavailable')
  }
  for (const entry of entries) {
    if (!entry.isFile() || !entry.name.endsWith('.yml')) continue
    const filename = path.join(providerDirectory, entry.name)
    let contents
    try {
      const stats = fs.lstatSync(filename)
      if (!stats.isFile() || stats.isSymbolicLink()) continue
      contents = fs.readFileSync(filename, 'utf8')
    } catch {
      throw invalid('Trusted provider sources are unavailable')
    }
    const match = /^id:\s*([a-z0-9][a-z0-9_-]*)\s*$/m.exec(contents)
    if (match) providerIds.add(match[1])
  }
  return providerIds
}

function providerId(value, knownIds, allowDiscovery = false) {
  if (allowDiscovery && value === '_discovery') return value
  if (typeof value !== 'string' || !PROVIDER_ID_PATTERN.test(value) || !knownIds.has(value))
    throw invalid('Invalid provider ID')
  return value
}

function providerIds(value, knownIds, allowDiscovery = false) {
  if (!Array.isArray(value)) throw invalid('Invalid provider list')
  return [...new Set(value.map((item) => providerId(item, knownIds, allowDiscovery)))].sort()
}

function validateTargetModel(value) {
  return safeText(value, 256, 'Invalid stored target model')
}

function optionalSourceURL(result) {
  if (!Object.hasOwn(result, 'source_url')) return undefined
  return sourceURL(result.source_url)
}

function validateClaimResponse(result, expectedRequestId) {
  if (!result || typeof result !== 'object' || Array.isArray(result) || typeof result.claimed !== 'boolean')
    throw invalid('Invalid claim response')
  const id = requestId(result.request_id)
  if (id !== expectedRequestId) throw invalid('Invalid claim response')
  const targetModel = validateTargetModel(result.target_model)
  const source = optionalSourceURL(result)
  return {
    claimed: result.claimed,
    request: result.claimed
      ? JSON.stringify({
          request_id: id,
          target_model: targetModel,
          ...(source === undefined ? {} : { source_url: source }),
        })
      : '{}',
  }
}

async function bridgeRequest(core, method, route, body, fetchImpl, expectsJSON = true) {
  let token
  try {
    token = await core.getIDToken(AUDIENCE)
  } catch {
    throw invalid('Price-check bridge authentication failed')
  }
  if (typeof token !== 'string' || token.length === 0 || /[\r\n]/.test(token))
    throw invalid('Price-check bridge authentication failed')

  let response
  try {
    const options = {
      method,
      headers: { authorization: `Bearer ${token}` },
    }
    if (body !== undefined) {
      options.headers['content-type'] = 'application/json'
      options.body = JSON.stringify(body)
    }
    response = await fetchImpl(`${BRIDGE_BASE}${route}`, options)
  } catch {
    throw invalid('Price-check bridge request failed')
  }
  if (!response || response.ok !== true) throw invalid('Price-check bridge request failed')
  if (!expectsJSON) return undefined
  try {
    return await response.json()
  } catch {
    throw invalid('Price-check bridge response was invalid')
  }
}

async function claimRequest({ core, context, fetchImpl = globalThis.fetch }) {
  const id = eventRequestId(context)
  const result = await bridgeRequest(core, 'POST', '/claim', { request_id: id }, fetchImpl)
  const claim = validateClaimResponse(result, id)
  core.setOutput('claimed', claim.claimed ? 'true' : 'false')
  core.setOutput('request', claim.request)
}

function validateBackfillResponse(result, knownIds) {
  if (!result || typeof result !== 'object' || Array.isArray(result) || !Array.isArray(result.pending))
    throw invalid('Invalid backfill response')
  return result.pending.map((item) => {
    if (!item || typeof item !== 'object' || Array.isArray(item)) throw invalid('Invalid backfill response')
    const record = {
      request_id: requestId(item.request_id),
      target_model: validateTargetModel(item.target_model),
      provider_id: providerId(item.provider_id, knownIds, true),
    }
    const source = optionalSourceURL(item)
    return { ...record, ...(source === undefined ? {} : { source_url: source }) }
  })
}

function groupBackfillRows(pending) {
  const byRequest = new Map()
  for (const row of pending) {
    const rows = byRequest.get(row.request_id) ?? []
    rows.push(row)
    byRequest.set(row.request_id, rows)
  }
  return [...byRequest.values()].map((rows) => {
    const source = rows.find((row) => Object.hasOwn(row, 'source_url'))?.source_url
    return rows.map((row, index) => {
      const { source_url: _sourceURL, ...record } = row
      return index === 0 && source !== undefined ? { ...record, source_url: source } : record
    })
  })
}

function boundBackfillRows(pending, runNumber) {
  const groups = groupBackfillRows(pending)
  if (groups.length === 0) return { rows: [], omitted: 0 }
  const rotation = Number.isSafeInteger(runNumber) && runNumber > 0 ? runNumber % groups.length : 0
  const rotated = [...groups.slice(rotation), ...groups.slice(0, rotation)]
  const selected = []
  let selectedGroups = 0
  let omitted = 0
  for (const group of rotated) {
    if (selectedGroups >= MAX_BACKFILL_REQUESTS) {
      omitted += 1
      continue
    }
    const candidate = [...selected, ...group]
    if (Buffer.byteLength(JSON.stringify(candidate), 'utf8') > MAX_BACKFILL_OUTPUT_BYTES) {
      omitted += 1
      continue
    }
    selected.push(...group)
    selectedGroups += 1
  }
  return { rows: selected, omitted }
}

async function readBackfill({ core, context, fetchImpl = globalThis.fetch }) {
  const result = await bridgeRequest(core, 'GET', '/backfill', undefined, fetchImpl)
  const pending = validateBackfillResponse(result, knownProviderIds())
  const batch = boundBackfillRows(pending, context?.runNumber)
  if (batch.omitted > 0)
    core.warning(
      `Backfill output omitted ${batch.omitted} request group(s) due to output limits; they remain pending.`,
    )
  core.setOutput('pending', JSON.stringify(batch.rows))
}

function reportDirectory(artifactDirectory, env) {
  if (artifactDirectory !== undefined) return artifactDirectory
  if (typeof env.RUNNER_TEMP !== 'string' || env.RUNNER_TEMP.length === 0) return undefined
  return path.join(env.RUNNER_TEMP, 'genie-pricer-artifacts')
}

function locateReport(directory) {
  if (directory === undefined) return { status: 'missing' }
  let rootStats
  try {
    rootStats = fs.lstatSync(directory)
  } catch {
    return { status: 'missing' }
  }
  if (!rootStats.isDirectory() || rootStats.isSymbolicLink()) return { status: 'invalid' }
  const found = []
  const visit = (current) => {
    let entries
    try {
      entries = fs.readdirSync(current, { withFileTypes: true })
    } catch {
      throw invalid('Invalid agent artifact')
    }
    for (const entry of entries) {
      const filename = path.join(current, entry.name)
      let stats
      try {
        stats = fs.lstatSync(filename)
      } catch {
        throw invalid('Invalid agent artifact')
      }
      if (stats.isSymbolicLink()) throw invalid('Invalid agent artifact')
      if (stats.isDirectory()) visit(filename)
      else if (!stats.isFile()) throw invalid('Invalid agent artifact')
      else if (entry.name === REPORT_NAME) {
        if (stats.size > MAX_REPORT_BYTES) throw invalid('Invalid agent artifact')
        found.push(filename)
      }
    }
  }
  try {
    visit(directory)
  } catch {
    return { status: 'invalid' }
  }
  if (found.length !== 1) return { status: found.length === 0 ? 'missing' : 'invalid' }
  try {
    const contents = fs.readFileSync(found[0])
    if (contents.byteLength > MAX_REPORT_BYTES) return { status: 'invalid' }
    return { status: 'found', contents: contents.toString('utf8') }
  } catch {
    return { status: 'invalid' }
  }
}

function parseJSONReport(directory) {
  const located = locateReport(directory)
  if (located.status !== 'found') return located
  try {
    const report = JSON.parse(located.contents)
    if (!report || typeof report !== 'object' || Array.isArray(report)) return { status: 'invalid' }
    return { status: 'found', report }
  } catch {
    return { status: 'invalid' }
  }
}

function validateTargetedReport(report, knownIds) {
  if (typeof report.summary !== 'string' || report.summary.length > 2000) throw invalid('Invalid agent report')
  return {
    summary: report.summary,
    pending_providers: providerIds(report.pending_providers, knownIds, true),
  }
}

function strictPrURL(value) {
  if (typeof value !== 'string' || !PR_URL_PATTERN.test(value)) return undefined
  let url
  try {
    url = new URL(value)
  } catch {
    return undefined
  }
  if (
    url.protocol !== 'https:' ||
    url.hostname !== 'github.com' ||
    url.port ||
    url.username ||
    url.password ||
    url.search ||
    url.hash
  )
    return undefined
  return value
}

function workflowSucceeded(env) {
  return env.AGENT_RESULT === 'success' && env.SAFE_OUTPUT_RESULT === 'success'
}

async function reportTargetedResult({
  core,
  context,
  fetchImpl = globalThis.fetch,
  artifactDirectory,
  env = process.env,
}) {
  const id = eventRequestId(context)
  const reportResult = parseJSONReport(reportDirectory(artifactDirectory, env))
  const knownIds = knownProviderIds()
  let report
  if (reportResult.status === 'found') {
    try {
      report = validateTargetedReport(reportResult.report, knownIds)
    } catch {
      report = undefined
    }
  }
  const prUrl = strictPrURL(env.CREATED_PR_URL)
  const state = prUrl ? 'proposed' : workflowSucceeded(env) && report ? 'complete' : 'failed'
  const pendingProviders = report?.pending_providers ?? ['_discovery']
  let summary =
    report?.summary ??
    'Incomplete: model-check-report.json is missing or invalid; provider discovery remains unresolved.'
  if (!report && prUrl)
    summary = `Incomplete: a pull request was created, but model-check-report.json is missing or invalid.`
  else if (report && !workflowSucceeded(env)) summary = `Incomplete: agent or safe outputs did not succeed. ${summary}`
  summary = summary.slice(0, 2000)
  await bridgeRequest(
    core,
    'POST',
    '/result',
    { request_id: id, state, pr_url: prUrl ?? null, summary, pending_providers: pendingProviders },
    fetchImpl,
    false,
  )
}

function expectedRequestIds(env) {
  const candidate = env.PENDING_BACKFILL
  if (candidate === undefined || candidate === null || candidate === '') return undefined
  let pending
  try {
    pending = JSON.parse(candidate)
  } catch {
    throw invalid('Invalid pending backfill input')
  }
  if (!Array.isArray(pending)) throw invalid('Invalid pending backfill input')
  const ids = pending.map((item) => requestId(item?.request_id))
  return [...new Set(ids)]
}

function validateBackfillResults(report, expectedIds, knownIds) {
  if (!Array.isArray(report.backfill_results)) throw invalid('Missing backfill results')
  const expected = new Set(expectedIds)
  const seen = new Set()
  const results = report.backfill_results.map((item) => {
    if (!item || typeof item !== 'object' || Array.isArray(item)) throw invalid('Invalid backfill results')
    const id = requestId(item.request_id)
    if (!expected.has(id) || seen.has(id)) throw invalid('Invalid backfill results')
    seen.add(id)
    const pending = providerIds(item.pending_providers, knownIds, true)
    const verified = providerIds(item.verified_providers, knownIds)
    const alreadyPresent =
      item.already_present_providers === undefined ? [] : providerIds(item.already_present_providers, knownIds)
    if ([...pending, ...verified, ...alreadyPresent].some((provider, index, all) => all.indexOf(provider) !== index))
      throw invalid('Invalid backfill results')
    return {
      request_id: id,
      pending_providers: pending,
      verified_providers: verified,
      already_present_providers: alreadyPresent,
    }
  })
  if (seen.size !== expected.size) throw invalid('Incomplete backfill results')
  return results
}

async function reportBackfill({ core, context, fetchImpl = globalThis.fetch, artifactDirectory, env = process.env }) {
  let expectedIds
  try {
    expectedIds = expectedRequestIds(env)
  } catch {
    core.warning('Backfill input is invalid; existing pending requests were left unchanged.')
    return
  }
  if (!expectedIds?.length) return

  const reportResult = parseJSONReport(reportDirectory(artifactDirectory, env))
  if (reportResult.status !== 'found') {
    core.warning('Backfill report is missing or invalid; existing pending requests were left unchanged.')
    return
  }
  let results
  try {
    const knownIds = knownProviderIds()
    results = validateBackfillResults(reportResult.report, expectedIds, knownIds)
  } catch {
    core.warning('Backfill report is invalid or incomplete; existing pending requests were left unchanged.')
    return
  }

  const successful = workflowSucceeded(env)
  if (!successful) {
    core.warning('Backfill run did not succeed; existing pending requests were left unchanged.')
    return
  }
  const prUrl = strictPrURL(env.CREATED_PR_URL)
  const verifiedPairs = prUrl
    ? results.flatMap((result) =>
        result.verified_providers.map((provider_id) => ({ request_id: result.request_id, provider_id })),
      )
    : []
  const resolvedPairs = results.flatMap((result) =>
    result.already_present_providers.map((provider_id) => ({ request_id: result.request_id, provider_id })),
  )
  const discoveries = results.map((result) => ({
    request_id: result.request_id,
    pending_providers: [...new Set([...result.pending_providers, ...result.verified_providers])].sort(),
  }))
  await bridgeRequest(
    core,
    'POST',
    '/backfill',
    { pr_url: prUrl ?? null, verified_pairs: verifiedPairs, discoveries, resolved_pairs: resolvedPairs },
    fetchImpl,
    false,
  )
}

module.exports = { claimRequest, readBackfill, reportBackfill, reportTargetedResult }
