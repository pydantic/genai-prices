import { calcPriceSync, calcPriceAsync } from '../dist/index.js'

const usage = { inputTokens: 1000, outputTokens: 100 }

console.log('--- Test: calcPriceSync with non-existent model ---')
try {
  calcPriceSync(usage, 'not-a-real-model')
  console.error('ERROR: Expected error for non-existent model (sync)')
} catch (e) {
  console.log('Caught expected error (sync):', e.message)
}

console.log('--- Test: calcPriceAsync with non-existent model ---')
calcPriceAsync(usage, 'not-a-real-model')
  .then(() => {
    console.error('ERROR: Expected error for non-existent model (async)')
  })
  .catch((e) => {
    console.log('Caught expected error (async):', e.message)
  })
  .then(async () => {
    console.log('--- Test: calcPriceSync before async (should throw if no data) ---')
    try {
      calcPriceSync(usage, 'gpt-3.5-turbo')
      console.error('ERROR: Expected error for sync before async')
    } catch (e) {
      console.log('Caught expected error (sync before async):', e.message)
    }

    console.log('--- Test: calcPriceAsync then calcPriceSync (should succeed) ---')
    try {
      const asyncResult = await calcPriceAsync(usage, 'gpt-3.5-turbo')
      console.log('Async result:', asyncResult.price, asyncResult.provider.name, asyncResult.model.name)
      const syncResult = calcPriceSync(usage, 'gpt-3.5-turbo')
      console.log('Sync result after async:', syncResult.price, syncResult.provider.name, syncResult.model.name)
    } catch (e) {
      console.error('ERROR: Unexpected error in async/sync test:', e.message)
    }

    console.log('--- Test: calcPriceAsync with providerId (should succeed) ---')
    try {
      const asyncResult = await calcPriceAsync(usage, 'gpt-3.5-turbo', { providerId: 'openai' })
      console.log(
        'Async result with providerId:',
        asyncResult.price,
        asyncResult.provider.name,
        asyncResult.model.name,
      )
    } catch (e) {
      console.error('ERROR: Unexpected error in async test with providerId:', e.message)
    }

    console.log('--- Test: calcPriceSync with providerId (should succeed) ---')
    try {
      const syncResult = calcPriceSync(usage, 'gpt-3.5-turbo', { providerId: 'openai' })
      console.log('Sync result with providerId:', syncResult.price, syncResult.provider.name, syncResult.model.name)
    } catch (e) {
      console.error('ERROR: Unexpected error in sync test with providerId:', e.message)
    }
  })
