/** Session-scoped home feed snapshot for return-from-detail restoration. */
import type { ImageView } from '../types'

const FEED_SESSION_KEY = 'vibelo-home-feed-session'
const FEED_SESSION_TTL = 20 * 60 * 1000

export interface FeedSession {
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
