import * as fs from 'fs'
import * as path from 'path'

import { calcPrice, updatePrices, Provider, waitForUpdate } from '../index'

// You can bump this to a longer TTL if you want to cache the data for longer
const PRICE_TTL = 1000 ///* 60 // * 60 * 60 * 24 // 24 hours

const GENAI_DATA_FILE = path.join(process.cwd(), '.genai-prices-cache.json')

updatePrices(async ({ remoteDataUrl, setProviderData }) => {
  try {
    const stats = fs.statSync(GENAI_DATA_FILE)
    const fileModTime = stats.mtime.getTime()

    if (Date.now() - fileModTime < PRICE_TTL) {
      console.log('cached file data is fresh')
      setProviderData(
        fs.promises.readFile(GENAI_DATA_FILE, 'utf-8').then((dataStr) => {
          return JSON.parse(dataStr) as Provider[]
        })
      )
      return
    } else {
      console.log('cached file data is stale, fetching fresh data')
    }
  } catch {
    console.log('no cached file found or error reading it, will fetch fresh data')
  }

  try {
    console.log('fetching fresh genai-prices data')
    const dataPromise = fetch(remoteDataUrl, { cache: 'no-store' }).then(async (response) => {
      return (await response.json()) as Provider[]
    })
    setProviderData(dataPromise)
    try {
      await fs.promises.writeFile(GENAI_DATA_FILE, JSON.stringify(await dataPromise, null, 2))
    } catch (writeError) {
      console.warn('Failed to write fresh data to file, will use it only in memory:', writeError)
    }
  } catch (error) {
    console.error('Failed to fetch remote genai-prices data:', error)
  }
})

await waitForUpdate()
const result1 = calcPrice({ input_tokens: 100, output_tokens: 100 }, 'gpt-3.5-turbo', {
  providerId: 'openai',
})

const result2 = calcPrice({ input_tokens: 100, output_tokens: 100 }, 'gpt-3.5-turbo', {
  providerId: 'openai',
})

const result3 = calcPrice({ input_tokens: 100, output_tokens: 100 }, 'gpt-3.5-turbo', {
  providerId: 'openai',
})

console.log('Async results:', [result1, result2, result3])
