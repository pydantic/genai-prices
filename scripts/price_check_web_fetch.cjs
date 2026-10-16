'use strict'

const { lookup } = require('node:dns/promises')
const { BlockList, isIP } = require('node:net')
const path = require('node:path')
const fs = require('node:fs')

const blocked = new BlockList()
for (const [address, prefix] of [
  ['0.0.0.0', 8],
  ['10.0.0.0', 8],
  ['100.64.0.0', 10],
  ['127.0.0.0', 8],
  ['169.254.0.0', 16],
  ['172.16.0.0', 12],
  ['192.0.0.0', 24],
  ['192.0.2.0', 24],
  ['192.88.99.0', 24],
  ['192.168.0.0', 16],
  ['198.18.0.0', 15],
  ['198.51.100.0', 24],
  ['203.0.113.0', 24],
  ['224.0.0.0', 4],
  ['240.0.0.0', 4],
])
  blocked.addSubnet(address, prefix, 'ipv4')
blocked.addAddress('168.63.129.16', 'ipv4')
for (const [address, prefix] of [
  ['::', 96],
  ['::1', 128],
  ['64:ff9b::', 96],
  ['64:ff9b:1::', 48],
  ['100::', 64],
  ['2001::', 23],
  ['2001:2::', 48],
  ['2001:db8::', 32],
  ['2002::', 16],
  ['3fff::', 20],
  ['fc00::', 7],
  ['fe80::', 10],
  ['ff00::', 8],
])
  blocked.addSubnet(address, prefix, 'ipv6')
const globalIPv6 = new BlockList()
globalIPv6.addSubnet('2000::', 3, 'ipv6')

async function validateURL(url, allowedHosts, resolve = lookup) {
  if (url.protocol !== 'https:' || url.port || url.username || url.password || !allowedHosts.has(url.hostname)) {
    throw new Error('web_fetch permits only manifest HTTPS origins on port 443 without credentials')
  }
  const addresses = await resolve(url.hostname, { all: true, verbatim: true })
  if (
    !addresses.length ||
    addresses.some(({ address }) => {
      const family = isIP(address)
      return (
        !family ||
        (family === 6 && !globalIPv6.check(address, 'ipv6')) ||
        blocked.check(address, family === 6 ? 'ipv6' : 'ipv4') ||
        (family === 6 && address.toLowerCase().includes(':5efe:'))
      )
    })
  )
    throw new Error('web_fetch refuses non-public DNS destinations')
}

async function fetchPage(input, allowedHosts, ghAw, options = {}) {
  const transport = ghAw.createWebFetchTransport(options)
  try {
    return await ghAw.executeCopilotSDKWebFetch(input, {
      fetchImpl: async (url, init) => {
        await validateURL(url, allowedHosts, options.resolve)
        const response = await transport.fetch(url, init)
        if (response.status >= 400) {
          await response.body?.cancel()
          throw new Error(`web_fetch received HTTP ${response.status} from ${url.hostname}`)
        }
        return response
      },
    })
  } finally {
    await transport.close()
  }
}

module.exports = { validateURL, fetchPage }

if (require.main === module) {
  ;(async () => {
    const { allowedHosts, ...input } = JSON.parse(fs.readFileSync(0, 'utf8'))
    if (!Array.isArray(allowedHosts) || !allowedHosts.every((host) => typeof host === 'string')) {
      throw new Error('Missing official source hosts')
    }
    const ghAw = require(path.join(process.env.RUNNER_TEMP, 'gh-aw/actions/copilot_sdk_web_fetch.cjs'))
    process.stdout.write(await fetchPage(input, new Set(allowedHosts), ghAw))
  })().catch((error) => {
    console.error(error.message)
    process.exitCode = 1
  })
}
