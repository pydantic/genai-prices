import * as fs from 'fs'
import * as path from 'path'

import { AsyncProviderStorage, calcPriceAsync, enableAutoUpdateForAsyncCalc, Provider } from '../index'

// You can bump this to a longer TTL if you want to cache the data for longer
const PRICE_TTL = 1000 * 60 // * 60 * 60 * 24 // 24 hours

const GENAI_DATA_FILE = path.join(process.cwd(), '.genai-prices-cache.json')

enableAutoUpdateForAsyncCalc(({ embeddedData, embeddedDataTimestamp, remoteDataUrl }) => {
  let dataPromise: null | Promise<Provider[]> = null

  const cb: AsyncProviderStorage = async () => {
    if (dataPromise) {
      console.log('using cached data promise')
      return dataPromise
    }

    if (Date.now() - embeddedDataTimestamp < PRICE_TTL) {
      console.log('genai prices data is fresh (embedded)')
      return Promise.resolve(embeddedData)
    }

    try {
      const stats = await fs.promises.stat(GENAI_DATA_FILE)
      const fileModTime = stats.mtime.getTime()

      if (Date.now() - fileModTime < PRICE_TTL) {
        console.log('cached file data is fresh')
        const dataStr = await fs.promises.readFile(GENAI_DATA_FILE, 'utf-8')
        const fileData: Provider[] = JSON.parse(dataStr) as Provider[]
        return fileData
      } else {
        console.log('cached file data is stale, fetching fresh data')
      }
    } catch {
      console.log('no cached file found or error reading it, will fetch fresh data')
    }

    try {
      console.log('fetching fresh genai data')
      dataPromise = fetch(remoteDataUrl, { cache: 'no-store' }).then(async (response) => {
        return (await response.json()) as Provider[]
      })
      try {
        await fs.promises.writeFile(GENAI_DATA_FILE, JSON.stringify(await dataPromise, null, 2))
      } catch (writeError) {
        console.warn('Failed to write fresh data to file, will use it only in memory:', writeError)
      }
    } catch (error) {
      console.error('Failed to fetch remote genai data:', error)
      // Try to use cached file data even if stale
      try {
        const dataStr = await fs.promises.readFile(GENAI_DATA_FILE, 'utf-8')
        const fileData: Provider[] = JSON.parse(dataStr) as Provider[]
        console.log('using stale cached file data as fallback')
        return fileData
      } catch (e) {
        console.warn('failed to read fallback cached file data', e)
      }

      return Promise.resolve(embeddedData)
    }

    return dataPromise
  }

  return cb
})

const result1 = calcPriceAsync({ input_tokens: 100, output_tokens: 100 }, 'gpt-3.5-turbo', {
  providerId: 'openai',
})

const result2 = calcPriceAsync({ input_tokens: 100, output_tokens: 100 }, 'gpt-3.5-turbo', {
  providerId: 'openai',
})

const result3 = calcPriceAsync({ input_tokens: 100, output_tokens: 100 }, 'gpt-3.5-turbo', {
  providerId: 'openai',
})

await Promise.all([result1, result2, result3]).then((results) => {
  console.log('Async results:', results)
})
