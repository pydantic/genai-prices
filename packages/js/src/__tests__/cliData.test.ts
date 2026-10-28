import { describe, expect, it, vi } from 'vitest'

import { REMOTE_DATA_JSON_URL } from '../api'
import { downloadProviderData } from '../cliData'

describe('CLI provider data download', () => {
  it('returns the raw downloaded JSON', async () => {
    const payload = [{ id: 'remote', prices: [{ constraint: { start_date: '2025-01-01' } }] }]
    const controller = new AbortController()
    try {
      vi.spyOn(AbortSignal, 'timeout').mockReturnValue(controller.signal)
      const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(new Response(JSON.stringify(payload)))
      vi.stubGlobal('fetch', fetchMock)

      await expect(downloadProviderData()).resolves.toEqual(payload)
      expect(fetchMock).toHaveBeenCalledExactlyOnceWith(REMOTE_DATA_JSON_URL, { signal: controller.signal })
    } finally {
      vi.restoreAllMocks()
      vi.unstubAllGlobals()
    }
  })

  it('rejects an unsuccessful HTTP response', async () => {
    try {
      vi.stubGlobal('fetch', vi.fn<typeof fetch>().mockResolvedValue(new Response('unavailable', { status: 503 })))

      await expect(downloadProviderData()).rejects.toThrow('HTTP 503')
    } finally {
      vi.restoreAllMocks()
      vi.unstubAllGlobals()
    }
  })

  it.each(['fetch', 'JSON body'])('rejects with the abort reason while %s never settles', async (phase) => {
    const controller = new AbortController()
    const reason = new DOMException('Download deadline expired', 'TimeoutError')
    try {
      vi.spyOn(AbortSignal, 'timeout').mockReturnValue(controller.signal)
      const enteredPhase = new Promise<void>((resolve) => {
        vi.stubGlobal(
          'fetch',
          vi.fn<typeof fetch>().mockImplementation(() => {
            if (phase === 'fetch') {
              resolve()
              return new Promise<Response>(() => {
                // Stay pending even when the download's signal aborts.
              })
            }
            const response = new Response()
            vi.spyOn(response, 'json').mockImplementation(() => {
              resolve()
              return new Promise<unknown>(() => {
                // Native body reads can ignore abort too.
              })
            })
            return Promise.resolve(response)
          })
        )
      })

      const rejection = expect(downloadProviderData()).rejects.toBe(reason)
      await enteredPhase
      controller.abort(reason)
      await rejection
    } finally {
      vi.restoreAllMocks()
      vi.unstubAllGlobals()
    }
  })
})
