import { describe, expect, it } from 'vitest'

import { formatPercent, formatPrice, formatUtc } from './format'

describe('format helpers', () => {
  it('formats missing prices safely', () => {
    expect(formatPrice(null)).toBe('—')
  })

  it('formats ratios as percentages', () => {
    expect(formatPercent(0.125)).toContain('12,5')
  })

  it('formats operational timestamps explicitly in UTC', () => {
    expect(formatUtc('2026-07-14T00:00:00Z')).toContain('UTC')
    expect(formatUtc(null)).toBe('—')
  })
})
