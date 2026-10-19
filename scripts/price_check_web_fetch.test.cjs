'use strict'

const assert = require('node:assert/strict')
const { test } = require('node:test')
const { validateURL, fetchPage } = require('./price_check_web_fetch.cjs')

const allowed = new Set(['pricing.example'])
const publicDNS = async () => [{ address: '93.184.216.34' }]

test('only verified official HTTPS origins are eligible', async () => {
  await validateURL(new URL('https://pricing.example/prices'), allowed, publicDNS)
  await validateURL(new URL('https://pricing.example/prices'), allowed, async () => [
    { address: '2001:4860:4860::8888' },
  ])
  for (const url of [
    'http://pricing.example/',
    'https://pricing.example:8443/',
    'https://user:secret@pricing.example/',
    'https://pricing.example.attacker.test/',
    'https://127.0.0.1/',
    'https://169.254.169.254/',
    'file:///etc/passwd',
  ])
    await assert.rejects(validateURL(new URL(url), allowed, publicDNS), /manifest HTTPS origins/)
})

test('official names resolving to private, metadata, mapped or transition addresses are rejected', async () => {
  for (const address of [
    '127.0.0.1',
    '10.1.2.3',
    '169.254.169.254',
    '168.63.129.16',
    '172.16.0.1',
    '192.168.1.1',
    '192.88.99.1',
    '100.100.100.200',
    '::1',
    '::ffff:127.0.0.1',
    '::ffff:169.254.169.254',
    '::ffff:168.63.129.16',
    '::127.0.0.1',
    'fd00::1',
    'fe80::1',
    'fec0::1',
    '3fff::1',
    '64:ff9b::7f00:1',
    '2002:7f00:1::',
    '2001:4860::5efe:7f00:1',
  ]) {
    await assert.rejects(
      validateURL(new URL('https://pricing.example/'), allowed, async () => [{ address }]),
      /non-public DNS/,
    )
  }
  await assert.rejects(
    validateURL(new URL('https://pricing.example/'), allowed, async () => []),
    /non-public DNS/,
  )
})

test('the public AWF transport receives hostname URLs and every redirect is checked', async () => {
  const requests = []
  let closes = 0
  const ghAw = {
    createWebFetchTransport: () => ({
      fetch: async (url) => {
        requests.push(url.href)
        return { status: 200 }
      },
      close: async () => {
        closes++
      },
    }),
    executeCopilotSDKWebFetch: async (input, { fetchImpl }) => {
      await fetchImpl(new URL(input.url), {})
      return 'official page'
    },
  }
  assert.equal(
    await fetchPage({ url: 'https://pricing.example/prices' }, allowed, ghAw, { resolve: publicDNS }),
    'official page',
  )
  assert.deepEqual(requests, ['https://pricing.example/prices'])
  ghAw.executeCopilotSDKWebFetch = async (input, { fetchImpl }) => {
    await fetchImpl(new URL(input.url), {})
    await fetchImpl(new URL('http://169.254.169.254/latest/meta-data'), {})
  }
  await assert.rejects(
    fetchPage({ url: 'https://pricing.example/' }, allowed, ghAw, { resolve: publicDNS }),
    /manifest HTTPS origins/,
  )
  assert.deepEqual(requests, ['https://pricing.example/prices', 'https://pricing.example/'])
  assert.equal(closes, 2)
})
