/** Home feed page with masonry layout and infinite scroll. */
import { RefreshCw } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { useAuth } from '../AuthContext'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { MasonryGrid } from '../components/MasonryGrid'
import { api } from '../services/api'
import type { ImageView } from '../types'
import { SearchPage } from './SearchPage'
import {
  clearFeedSession,
  readFeedSession,
  readRecentFeedIds,
  readRecentInteractedIds,
  rememberRecentFeedIds,
  rememberRecentInteractedIds,
  updateFeedScroll,
  writeFeedSession,
} from '../utils/feedSession'
import { getVisitorId } from '../utils/visitorIdentity'

const pageSize = 24

function createRefreshSeed() {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) return crypto.randomUUID()
  return `${Date.now()}-${Math.random().toString(36).slice(2)}`
}

function localOccurredAt() {
  const now = new Date()
  return new Date(now.getTime() - now.getTimezoneOffset() * 60_000).toISOString().slice(0, 23)
}

function isBrowserReload() {
  const navigation = performance.getEntriesByType?.('navigation')?.[0] as PerformanceNavigationTiming | undefined
  return navigation?.type === 'reload'
}

function uniqueIds(ids: number[], limit = 180) {
  const seen = new Set<number>()
  return ids.filter((id) => {
    if (!Number.isFinite(id) || id <= 0 || seen.has(id)) return false
    seen.add(id)
    return true
  }).slice(0, limit)
}

export function FeedPage() {
  const auth = useAuth()
  const initialSessionRef = useRef(isBrowserReload() ? null : readFeedSession())
  const visitorIdRef = useRef(getVisitorId())
  const feedSessionIdRef = useRef(initialSessionRef.current?.feedSessionId ?? createRefreshSeed())
  const refreshSeedRef = useRef(initialSessionRef.current?.refreshSeed ?? createRefreshSeed())
  const restoredScrollRef = useRef(false)
  const [images, setImages] = useState<ImageView[]>(() => initialSessionRef.current?.images ?? [])
  const [page, setPage] = useState(() => initialSessionRef.current?.page ?? 1)
  const [total, setTotal] = useState(() => initialSessionRef.current?.total ?? 0)
  const [loadedOnce, setLoadedOnce] = useState(() => initialSessionRef.current?.loadedOnce ?? false)
  const [exhausted, setExhausted] = useState(() => initialSessionRef.current?.exhausted ?? false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const sentinelRef = useRef<HTMLDivElement | null>(null)
  const loadingRef = useRef(false)
  const requestedPagesRef = useRef<Set<number>>(new Set())
  const loadedImageIdsRef = useRef<Set<number>>(new Set(initialSessionRef.current?.images.map((image) => image.id) ?? []))
  const impressionIdsRef = useRef<Set<string>>(new Set())
  const impressionQueueRef = useRef<Array<{
    imageId: number
    behaviorType: string
    scene: string
    position?: number
    decisionId: string
    eventId: string
    source: string
    occurredAt: string
  }>>([])
  const impressionTimerRef = useRef<number | null>(null)
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const searchKeyword = params.get('q')?.trim() || ''

  const hasMore = loadedOnce && !exhausted

  const flushImpressions = useCallback(() => {
    if (impressionTimerRef.current !== null) window.clearTimeout(impressionTimerRef.current)
    impressionTimerRef.current = null
    const events = impressionQueueRef.current.splice(0)
    if (events.length === 0) return
    void api.trackBehaviors(events, visitorIdRef.current).catch(() => undefined)
  }, [])

  const queueImpression = useCallback((image: ImageView) => {
    const decisionId = image.recommendationDecisionId
    if (!decisionId) return
    const eventId = `${decisionId}:${image.id}`
    if (impressionIdsRef.current.has(eventId)) return
    impressionIdsRef.current.add(eventId)
    impressionQueueRef.current.push({
      imageId: image.id,
      behaviorType: 'impression',
      scene: 'home',
      position: image.recommendationPosition,
      decisionId,
      eventId,
      source: image.recommendationReason || 'home',
      occurredAt: localOccurredAt(),
    })
    if (impressionQueueRef.current.length >= 12) {
      flushImpressions()
      return
    }
    if (impressionTimerRef.current === null) {
      impressionTimerRef.current = window.setTimeout(flushImpressions, 500)
    }
  }, [flushImpressions])

  useEffect(() => () => flushImpressions(), [flushImpressions])

  const loadPage = useCallback(async (targetPage: number, reset = false) => {
    if (loadingRef.current) return
    if (!reset && requestedPagesRef.current.has(targetPage)) return
    if (reset) requestedPagesRef.current.clear()
    requestedPagesRef.current.add(targetPage)
    loadingRef.current = true
    setLoading(true)
    setError('')

    try {
      const excludeIds = targetPage === 1
        ? uniqueIds([...readRecentInteractedIds(), ...readRecentFeedIds()])
        : uniqueIds(Array.from(loadedImageIdsRef.current), 240)
      const response = await api.homeFeed(targetPage, pageSize, refreshSeedRef.current, feedSessionIdRef.current, visitorIdRef.current, excludeIds)
      const decisionId = createRefreshSeed()
      const pageRecords = response.records.map((image, index) => ({
        ...image,
        recommendationDecisionId: decisionId,
        recommendationPosition: (targetPage - 1) * pageSize + index + 1,
      }))
      setTotal(response.total)
      setPage(targetPage + 1)
      setLoadedOnce(true)
      setExhausted(pageRecords.length === 0)

      if (pageRecords.length > 0) {
        rememberRecentFeedIds(pageRecords.map((image) => image.id))
      }

      setImages((current) => {
        const base = reset ? [] : current
        const seen = new Set(base.map((image) => image.id))
        const next = [...base, ...pageRecords.filter((image) => !seen.has(image.id))]
        loadedImageIdsRef.current = new Set(next.map((image) => image.id))

        return next
      })
      if (auth.user && pageRecords.length > 0) {
        void api.interactionStatuses(pageRecords.map((image) => image.id)).then((states) => {
          setImages((current) => current.map((image) => {
            const state = states[String(image.id)]
            return state ? { ...image, likedByMe: state.liked } : image
          }))
        }).catch(() => undefined)
      }
    } catch (reason) {
      requestedPagesRef.current.delete(targetPage)
      setLoadedOnce(true)
      setError(reason instanceof Error ? reason.message : '图片流加载失败')
    } finally {
      loadingRef.current = false
      setLoading(false)
    }
  }, [auth.user?.id])

  useEffect(() => {
    if (searchKeyword) return
    if (!initialSessionRef.current) void loadPage(1, true)
  }, [loadPage, searchKeyword])

  useEffect(() => {
    writeFeedSession({ feedSessionId: feedSessionIdRef.current, images, page, total, refreshSeed: refreshSeedRef.current, loadedOnce, exhausted, scrollY: window.scrollY })
  }, [exhausted, images, loadedOnce, page, total])

  useEffect(() => {
    const save = () => updateFeedScroll()
    window.addEventListener('pagehide', save)
    window.addEventListener('beforeunload', save)
    return () => {
      save()
      window.removeEventListener('pagehide', save)
      window.removeEventListener('beforeunload', save)
    }
  }, [])

  useEffect(() => {
    const session = initialSessionRef.current
    if (!session || restoredScrollRef.current || images.length === 0) return
    restoredScrollRef.current = true
    let frame = 0
    const restore = () => {
      frame = requestAnimationFrame(() => {
        window.scrollTo({ top: session.scrollY, left: 0, behavior: 'auto' })
      })
    }
    restore()
    const timer = window.setTimeout(restore, 80)
    return () => {
      cancelAnimationFrame(frame)
      window.clearTimeout(timer)
    }
  }, [images.length])

  useEffect(() => {
    if (searchKeyword) return
    const target = sentinelRef.current
    if (!target) return
    const observer = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting) && hasMore && !loadingRef.current) void loadPage(page)
    }, { rootMargin: '560px 0px' })
    observer.observe(target)
    return () => observer.disconnect()
  }, [hasMore, loadPage, page, searchKeyword])

  function openImage(image: ImageView) {
    const position = images.findIndex((item) => item.id === image.id) + 1
    rememberRecentInteractedIds([image.id])
    writeFeedSession({ feedSessionId: feedSessionIdRef.current, images, page, total, refreshSeed: refreshSeedRef.current, loadedOnce, exhausted, scrollY: window.scrollY })
    navigate(`/image/${image.id}`, { state: { previewImage: image, from: 'home' } })
    void api.trackImageClick(image.id, 'home', position, visitorIdRef.current).catch(() => undefined)
  }

  function reloadFeed() {
    requestedPagesRef.current.clear()
    clearFeedSession()
    feedSessionIdRef.current = createRefreshSeed()
    refreshSeedRef.current = createRefreshSeed()
    initialSessionRef.current = null
    restoredScrollRef.current = false
    loadedImageIdsRef.current = new Set()
    impressionIdsRef.current.clear()
    impressionQueueRef.current = []
    if (impressionTimerRef.current !== null) window.clearTimeout(impressionTimerRef.current)
    impressionTimerRef.current = null
    setImages([])
    setTotal(0)
    setPage(1)
    setLoadedOnce(false)
    setExhausted(false)
    window.scrollTo({ top: 0, behavior: 'smooth' })
    void loadPage(1, true)
  }

  if (searchKeyword) return <SearchPage />

  return (
    <div className="feed-page">
      <main className="feed-page__main">
        <MasonryGrid
          posts={images}
          loading={loading && images.length === 0}
          emptyLabel={loading ? '正在加载图片...' : '还没有图片'}
          onImpression={queueImpression}
          onOpen={openImage}
        />
        {error && (
          <div className="feed-page__state">
            <span>{error}</span>
            <button type="button" onClick={reloadFeed}>
              <RefreshCw size={15} />
              重新加载
            </button>
          </div>
        )}
        <div ref={sentinelRef} className="feed-page__sentinel" />
        {loading && images.length > 0 && <div className="feed-page__loading"><span /><span /><span /></div>}
        {!loading && images.length > 0 && !hasMore && <p className="feed-page__ending">已经到底了</p>}
      </main>
    </div>
  )
}
