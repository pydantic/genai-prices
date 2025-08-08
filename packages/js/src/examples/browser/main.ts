import {
  AsyncProviderStorage,
  calcPriceAsync,
  calcPriceSync,
  enableAutoUpdateForAsyncCalc,
  enableAutoUpdateForSyncCalc,
  Provider,
} from '../..'

const PRICE_TTL = 1000 * 60 // * 60 * 60 * 24 // 24 hours

const GENAI_DATA_KEY = 'genai-prices-data'
const GENAI_DATA_TIMESTAMP_KEY = 'genai-prices-timestamp'

enableAutoUpdateForSyncCalc(({ embeddedData, embeddedDataTimestamp, remoteDataUrl }) => {
  let data = embeddedData
  const cb = () => {
    return data
  }

  if (Date.now() - embeddedDataTimestamp < PRICE_TTL) {
    console.log('genai prices data is fresh')
    return cb
  }

  try {
    const localStorageDataTimestamp = localStorage.getItem('genai-prices-timestamp')
    // we have a fresh data in the local storage.
    if (localStorageDataTimestamp !== null) {
      console.log('we have data in local storage')

      const dataStr = localStorage.getItem(GENAI_DATA_KEY)
      if (dataStr !== null) {
        data = JSON.parse(dataStr) as Provider[]
      }

      if (Date.now() - parseInt(localStorageDataTimestamp, 10) < PRICE_TTL) {
        console.log('local storage data is fresh')
        return cb
      } else {
        console.log('local storage data is stale, continuing to fetch remote data')
      }
    }
  } catch (e) {
    console.log('failed to read local storage, using embedded data', e)
    return cb
  }

  console.log('genai-prices data is stale')

  // at this point, we have no fresh data in the local storage, so we will fetch remote data.
  // we will use the current data (either the embedded one or the stale local storage one) as a temp fallback.
  fetch(remoteDataUrl, { cache: 'no-store' })
    .then(async (response) => {
      const freshData = (await response.json()) as Provider[]
      console.log('updated genai-prices data')
      try {
        localStorage.setItem(GENAI_DATA_TIMESTAMP_KEY, Date.now().toString())
        localStorage.setItem(GENAI_DATA_KEY, JSON.stringify(freshData))
      } catch {
        // we can ignore local storage errors, as we have a fallback to the embedded data
      }
      data = freshData
    })
    .catch((error: unknown) => {
      console.error('Failed to fetch remote genai-prices data, using what we have:', error)
      // we failed to fetch remote data, so we will use the current data as a fallback
      return cb
    })
  return cb
})

enableAutoUpdateForAsyncCalc(({ embeddedData, embeddedDataTimestamp, remoteDataUrl }) => {
  let dataPromise: null | Promise<Provider[]> = null

  const safeLocalStorage = {
    getItem: (key: string): null | string => {
      try {
        return localStorage.getItem(key)
      } catch (e) {
        console.warn('localStorage.getItem failed:', e)
        return null
      }
    },
    setItem: (key: string, value: string): void => {
      try {
        localStorage.setItem(key, value)
      } catch (e) {
        console.warn('localStorage.setItem failed:', e)
      }
    },
  }

  const fetchFreshData: AsyncProviderStorage = async () => {
    try {
      console.log('fetching fresh genai data')
      const response = await fetch(remoteDataUrl, { cache: 'no-store' })
      const freshData = (await response.json()) as Provider[]

      console.log('updated genai data')
      safeLocalStorage.setItem(GENAI_DATA_TIMESTAMP_KEY, Date.now().toString())
      safeLocalStorage.setItem(GENAI_DATA_KEY, JSON.stringify(freshData))

      return freshData
    } catch (error) {
      console.error('Failed to fetch remote genai data:', error)
      throw error
    }
  }

  const cb: AsyncProviderStorage = async () => {
    // If we already have a promise in flight, return it
    if (dataPromise) {
      return dataPromise
    }

    // Check if embedded data is fresh
    if (Date.now() - embeddedDataTimestamp < PRICE_TTL) {
      console.log('genai prices data is fresh (embedded)')
      return Promise.resolve(embeddedData)
    }

    // Check localStorage for fresh data
    const localStorageDataTimestamp = safeLocalStorage.getItem(GENAI_DATA_TIMESTAMP_KEY)
    if (localStorageDataTimestamp !== null) {
      const dataStr = safeLocalStorage.getItem(GENAI_DATA_KEY)
      if (dataStr !== null) {
        try {
          const localData: Provider[] = JSON.parse(dataStr) as Provider[]
          if (Date.now() - parseInt(localStorageDataTimestamp, 10) < PRICE_TTL) {
            console.log('local storage data is fresh')
            return localData
          } else {
            console.log('local storage data is stale, fetching fresh data')
          }
        } catch (e) {
          console.warn('failed to parse local storage data', e)
        }
      }
    }

    // Data is stale, fetch fresh data (with promise caching)
    dataPromise = fetchFreshData()
      .catch((error: unknown) => {
        // If fetch fails, fall back to best available data
        console.error('Failed to fetch fresh data, falling back:', error)

        // Try to use local storage data even if stale
        const dataStr = safeLocalStorage.getItem(GENAI_DATA_KEY)
        if (dataStr !== null) {
          try {
            return JSON.parse(dataStr) as Provider[]
          } catch (e) {
            console.warn('failed to parse fallback local storage data', e)
          }
        }

        // Final fallback to embedded data
        return Promise.resolve(embeddedData)
      })
      .finally(() => {
        // Clear the promise so future calls can fetch again if needed
        dataPromise = null
      })

    return dataPromise
  }

  return cb
})

calcPriceSync({ input_tokens: 100, output_tokens: 100 }, 'gpt-3.5-turbo', {
  providerId: 'openai',
})

calcPriceSync({ input_tokens: 100, output_tokens: 100 }, 'gpt-3.5-turbo', {
  providerId: 'openai',
})

setTimeout(() => {
  const result = calcPriceSync({ input_tokens: 100, output_tokens: 100 }, 'gpt-3.5-turbo', {
    providerId: 'openai',
  })
  console.log(result)
}, 100)

async function testAsyncPrice() {
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
}

await testAsyncPrice()
