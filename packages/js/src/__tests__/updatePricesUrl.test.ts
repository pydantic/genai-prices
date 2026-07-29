import { describe, expect, it } from 'vitest'

import { updatePrices } from '../api'

describe('updatePrices', () => {
  it('passes the v2 provider-array URL to the storage factory', () => {
    let remoteDataUrl: string | undefined

    updatePrices((options) => {
      remoteDataUrl = options.remoteDataUrl
    })

    expect(remoteDataUrl).toBe('https://raw.githubusercontent.com/pydantic/genai-prices/main/prices/data_v2.json')
  })
})
