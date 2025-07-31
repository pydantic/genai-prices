#!/usr/bin/env node

import { calcPriceSync } from '../dist/index.js'

console.log('Testing with existing model:')
try {
  const result = calcPriceSync({ inputTokens: 1000, outputTokens: 500 }, 'gpt-4')
  if (result) {
    console.log('Success:', result.price)
  } else {
    console.log('No price found for gpt-4')
  }
} catch (e) {
  console.log('Error:', e.message)
  console.log('Stack:', e.stack)
}

console.log('\nTesting with non-existent model:')
try {
  const result = calcPriceSync({ inputTokens: 1000, outputTokens: 500 }, 'non-existent-model')
  if (result) {
    console.log('Success:', result.price)
  } else {
    console.log('No price found for non-existent-model')
  }
} catch (e) {
  console.log('Error:', e.message)
  console.log('Stack:', e.stack)
}
