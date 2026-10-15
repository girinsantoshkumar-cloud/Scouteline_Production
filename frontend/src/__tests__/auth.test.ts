import { beforeEach, describe, expect, it } from 'vitest'
import { clearSession, getToken, getUser, setSession } from '../auth'

const user = { id: '1', name: 'Ann Lee', email: 'ann@example.com', created_at: '2026-01-01T00:00:00Z' }

describe('session helpers', () => {
  beforeEach(() => localStorage.clear())

  it('returns null when no session is stored', () => {
    expect(getToken()).toBeNull()
    expect(getUser()).toBeNull()
  })

  it('stores and reads a session', () => {
    setSession('tok', user)
    expect(getToken()).toBe('tok')
    expect(getUser()).toEqual(user)
  })

  it('clears the session', () => {
    setSession('tok', user)
    clearSession()
    expect(getToken()).toBeNull()
    expect(getUser()).toBeNull()
  })

  it('ignores corrupt stored user JSON', () => {
    localStorage.setItem('scoutline.user', '{not json')
    expect(getUser()).toBeNull()
  })
})
