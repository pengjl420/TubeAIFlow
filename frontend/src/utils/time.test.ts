import { describe, expect, it } from 'vitest'

import { formatDateTime, formatDuration } from './time'


describe('time formatting', () => {
  it('formats short and long durations without negative output', () => {
    expect(formatDuration(65)).toBe('01:05')
    expect(formatDuration(3661)).toBe('1:01:01')
    expect(formatDuration(-5)).toBe('00:00')
  })

  it('uses the fallback for missing or invalid values', () => {
    expect(formatDuration(Number.NaN, 'n/a')).toBe('n/a')
    expect(formatDateTime('not-a-date', 'n/a')).toBe('n/a')
  })
})
