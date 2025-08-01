import { calcPriceSync, calcPriceAsync } from '../dist/index.js'

const usage = { input_tokens: 1000, output_tokens: 100 }

console.log('--- Test: calcPriceSync with non-existent model ---')
const syncResult = calcPriceSync(usage, 'not-a-real-model')
if (syncResult === null) {
  console.log('Correctly returned null for non-existent model (sync)')
} else {
  console.error('ERROR: Expected null for non-existent model (sync)')
}

console.log('--- Test: calcPriceAsync with non-existent model ---')
calcPriceAsync(usage, 'not-a-real-model')
  .then((result) => {
    if (result === null) {
      console.log('Correctly returned null for non-existent model (async)')
    } else {
      console.error('ERROR: Expected null for non-existent model (async)')
    }
  })
  .then(async () => {
    console.log('--- Test: calcPriceSync before async (should return null if no data) ---')
    const syncResultBeforeAsync = calcPriceSync(usage, 'gpt-3.5-turbo')
    if (syncResultBeforeAsync === null) {
      console.log('Correctly returned null for sync before async (no embedded data)')
    } else {
      console.log(
        'Sync result before async:',
        `$${syncResultBeforeAsync.total_price} (input: $${syncResultBeforeAsync.input_price}, output: $${syncResultBeforeAsync.output_price})`,
        syncResultBeforeAsync.provider.name,
        syncResultBeforeAsync.model.name,
      )
    }

    console.log('--- Test: calcPriceAsync then calcPriceSync (should succeed) ---')
    try {
      const asyncResult = await calcPriceAsync(usage, 'gpt-3.5-turbo')
      if (asyncResult) {
        console.log(
          'Async result:',
          `$${asyncResult.total_price} (input: $${asyncResult.input_price}, output: $${asyncResult.output_price})`,
          asyncResult.provider.name,
          asyncResult.model.name,
        )
        const syncResult = calcPriceSync(usage, 'gpt-3.5-turbo')
        if (syncResult) {
          console.log(
            'Sync result after async:',
            `$${syncResult.total_price} (input: $${syncResult.input_price}, output: $${syncResult.output_price})`,
            syncResult.provider.name,
            syncResult.model.name,
          )
        } else {
          console.log('Sync result after async: null (no embedded data)')
        }
      } else {
        console.log('Async result: null (no price found)')
      }
    } catch (e) {
      console.error('ERROR: Unexpected error in async/sync test:', e.message)
    }

    console.log('--- Test: calcPriceAsync with providerId (should succeed) ---')
    try {
      const asyncResult = await calcPriceAsync(usage, 'gpt-3.5-turbo', { providerId: 'openai' })
      if (asyncResult) {
        console.log(
          'Async result with providerId:',
          `$${asyncResult.total_price} (input: $${asyncResult.input_price}, output: $${asyncResult.output_price})`,
          asyncResult.provider.name,
          asyncResult.model.name,
        )
      } else {
        console.log('Async result with providerId: null (no price found)')
      }
    } catch (e) {
      console.error('ERROR: Unexpected error in async test with providerId:', e.message)
    }

    console.log('--- Test: calcPriceSync with providerId (should succeed) ---')
    try {
      const syncResult = calcPriceSync(usage, 'gpt-3.5-turbo', { providerId: 'openai' })
      if (syncResult) {
        console.log(
          'Sync result with providerId:',
          `$${syncResult.total_price} (input: $${syncResult.input_price}, output: $${syncResult.output_price})`,
          syncResult.provider.name,
          syncResult.model.name,
        )
      } else {
        console.log('Sync result with providerId: null (no price found)')
      }
    } catch (e) {
      console.error('ERROR: Unexpected error in sync test with providerId:', e.message)
    }
  })
