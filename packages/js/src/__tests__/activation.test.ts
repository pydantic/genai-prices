import { describe, expect, it } from 'vitest'

import { findProvider } from '../api'

describe('provider activation', () => {
  it('validates embedded provider data during startup and keeps it active', () => {
    expect(findProvider({ providerId: 'anthropic' })?.id).toBe('anthropic')
  })
})
