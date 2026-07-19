import { describe, it, expect, vi, afterEach } from 'vitest'
import { formatRelativeTime } from './format'

describe('formatRelativeTime', () => {
  afterEach(() => {
    vi.useRealTimers()
  })

  it('returns empty string for empty input', () => {
    expect(formatRelativeTime('')).toBe('')
  })

  it('returns empty string for an invalid date', () => {
    expect(formatRelativeTime('not-a-date')).toBe('')
  })

  it('renders "刚刚" for a timestamp less than a minute ago', () => {
    vi.setSystemTime(new Date('2026-07-14T12:00:00Z'))
    expect(formatRelativeTime('2026-07-14T11:59:30Z')).toBe('刚刚')
  })

  it('renders minutes for a timestamp within the hour', () => {
    vi.setSystemTime(new Date('2026-07-14T12:00:00Z'))
    expect(formatRelativeTime('2026-07-14T11:45:00Z')).toBe('15分钟前')
  })

  it('renders hours for a timestamp within the day', () => {
    vi.setSystemTime(new Date('2026-07-14T12:00:00Z'))
    expect(formatRelativeTime('2026-07-14T09:00:00Z')).toBe('3小时前')
  })

  it('renders days for a timestamp older than a day', () => {
    vi.setSystemTime(new Date('2026-07-14T12:00:00Z'))
    expect(formatRelativeTime('2026-07-12T12:00:00Z')).toBe('2天前')
  })
})
