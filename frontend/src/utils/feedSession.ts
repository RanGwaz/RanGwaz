/** Session-scoped home feed snapshot for return-from-detail restoration. */
import type { ImageView } from '../types'

const FEED_SESSION_KEY = 'vibelo-home-feed-session'
const FEED_RECENT_IDS_KEY = 'vibelo-home-feed-recent-ids'
const FEED_INTERACTED_IDS_KEY = 'vibelo-home-feed-interacted-ids'
const FEED_SESSION_TTL = 20 * 60 * 1000
const FEED_RECENT_IDS_TTL = 30 * 60 * 1000
const FEED_INTERACTED_IDS_TTL = 48 * 60 * 60 * 1000

export interface FeedSession {
  feedSessionId: string
  images: ImageView[]
  page: number
  total: number
  refreshSeed: string
  loadedOnce: boolean
  exhausted: boolean
  scrollY: number
  savedAt: number
}

export function readFeedSession(): FeedSession | null {
  try {
    const raw = sessionStorage.getItem(FEED_SESSION_KEY)
    if (!raw) return null
    const value = JSON.parse(raw) as FeedSession
    const isExpired = Date.now() - Number(value.savedAt || 0) > FEED_SESSION_TTL
    const isEmptyBeforeLoad = !value.loadedOnce || !Array.isArray(value.images) || value.images.length === 0
    if (isExpired || isEmptyBeforeLoad) {
      sessionStorage.removeItem(FEED_SESSION_KEY)
      return null
    }
    if (!value.feedSessionId) value.feedSessionId = value.refreshSeed
    return value
  } catch {
    sessionStorage.removeItem(FEED_SESSION_KEY)
    return null
  }
}

export function writeFeedSession(value: Omit<FeedSession, 'savedAt'>) {
  if (!value.loadedOnce && value.images.length === 0) return
  sessionStorage.setItem(FEED_SESSION_KEY, JSON.stringify({ ...value, savedAt: Date.now() }))
}

export function clearFeedSession() {
  sessionStorage.removeItem(FEED_SESSION_KEY)
}

export function updateFeedScroll(scrollY = window.scrollY) {
  const current = readFeedSession()
  if (!current) return
  writeFeedSession({ ...current, scrollY })
}

export function readRecentFeedIds(limit = 160) {
  return readRecentIds(FEED_RECENT_IDS_KEY, FEED_RECENT_IDS_TTL, limit)
}

export function rememberRecentFeedIds(ids: number[], limit = 240) {
  rememberRecentIds(FEED_RECENT_IDS_KEY, FEED_RECENT_IDS_TTL, ids, limit)
}

export function readRecentInteractedIds(limit = 240) {
  return readRecentIds(FEED_INTERACTED_IDS_KEY, FEED_INTERACTED_IDS_TTL, limit)
}

export function rememberRecentInteractedIds(ids: number[], limit = 240) {
  rememberRecentIds(FEED_INTERACTED_IDS_KEY, FEED_INTERACTED_IDS_TTL, ids, limit)
}

function readRecentIds(key: string, ttl: number, limit: number) {
  try {
    const raw = localStorage.getItem(key)
    if (!raw) return []
    const value = JSON.parse(raw) as { ids?: number[]; savedAt?: number }
    const isExpired = Date.now() - Number(value.savedAt || 0) > ttl
    if (isExpired || !Array.isArray(value.ids)) {
      localStorage.removeItem(key)
      return []
    }
    return value.ids.filter((id) => Number.isFinite(id) && id > 0).slice(0, limit)
  } catch {
    localStorage.removeItem(key)
    return []
  }
}

function rememberRecentIds(key: string, ttl: number, ids: number[], limit: number) {
  const current = readRecentIds(key, ttl, limit)
  const seen = new Set<number>()
  const next = [...ids, ...current].filter((id) => {
    if (!Number.isFinite(id) || id <= 0 || seen.has(id)) return false
    seen.add(id)
    return true
  }).slice(0, limit)
  localStorage.setItem(key, JSON.stringify({ ids: next, savedAt: Date.now() }))
}
