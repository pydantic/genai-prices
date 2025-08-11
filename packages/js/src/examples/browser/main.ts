import { calcPrice, updatePrices, Provider } from '../..'

const PRICE_TTL = 1000 * 60 // * 60 * 60 * 24 // 24 hours

const GENAI_DATA_KEY = 'genai-prices-data'
const GENAI_DATA_TIMESTAMP_KEY = 'genai-prices-timestamp'

updatePrices(({ onCalc, remoteDataUrl, setProviderData }) => {
  onCalc(() => {
    // you can implement a stale/refresh check to capture stale data and eventually set new provider data (as promise)
    console.log('calculation is happening')
  })

  try {
    const localStorageDataTimestamp = localStorage.getItem('genai-prices-timestamp')
    // we have a fresh data in the local storage.
    if (localStorageDataTimestamp !== null) {
      console.log('we have data in local storage')

      const dataStr = localStorage.getItem(GENAI_DATA_KEY)
      if (dataStr !== null) {
        setProviderData(JSON.parse(dataStr) as Provider[])
      }

      if (Date.now() - parseInt(localStorageDataTimestamp, 10) < PRICE_TTL) {
        console.log('local storage data is fresh')
        return
      } else {
        console.log('local storage data is stale, continuing to fetch remote data')
      }
    }
  } catch (e) {
    console.log('failed to read local storage, using embedded data', e)
    return
  }

  console.log('genai-prices data is stale')

  // at this point, we have no fresh data in the local storage, so we will fetch remote data.
  // we will use the current data (either the embedded one or the stale local storage one) as a temp fallback.
  setProviderData(
    fetch(remoteDataUrl, { cache: 'no-store' }).then(async (response) => {
      const freshData = (await response.json()) as Provider[]
      console.log('updated genai-prices data')
      try {
        localStorage.setItem(GENAI_DATA_TIMESTAMP_KEY, Date.now().toString())
        localStorage.setItem(GENAI_DATA_KEY, JSON.stringify(freshData))
      } catch {
        // we can ignore local storage errors, as we have a fallback to the embedded data
      }
      return freshData
    })
  )
})

calcPrice({ input_tokens: 100, output_tokens: 100 }, 'gpt-3.5-turbo', {
  providerId: 'openai',
})

calcPrice({ input_tokens: 100, output_tokens: 100 }, 'gpt-3.5-turbo', {
  providerId: 'openai',
})

setTimeout(() => {
  const result = calcPrice({ input_tokens: 100, output_tokens: 100 }, 'gpt-3.5-turbo', {
    providerId: 'openai',
  })
  console.log(result)
}, 100)
