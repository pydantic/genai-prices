#!/usr/bin/env node

import { calcPriceSync } from '../dist/index.js'

try {
  const result = calcPriceSync({ inputTokens: 1000, outputTokens: 500 }, 'gpt-4')
  console.log('Success:', result.price)
} catch (e) {
  console.log('Error:', e.message)
  console.log('Stack:', e.stack)
}
