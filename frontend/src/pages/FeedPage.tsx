/** Home feed page with masonry layout and infinite scroll. */
import { RefreshCw } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { MasonryGrid } from '../components/MasonryGrid'
import { api } from '../services/api'
import type { ImageView } from '../types'

const pageSize = 30

export function FeedPage() {
  const [images, setImages] = useState<ImageView[]>([])
  const [page, setPage] = useState(1)
  const [total, setTotal] = useState(0)
  const [loadedOnce, setLoadedOnce] = useState(false)
  const [exhausted, setExhausted] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const sentinelRef = useRef<HTMLDivElement | null>(null)
  const loadingRef = useRef(false)
  const requestedPagesRef = useRef<Set<number>>(new Set())
  const navigate = useNavigate()

  const hasMore = loadedOnce && !exhausted && images.length < total

  const loadPage = useCallback(async (targetPage: number, reset = false) => {
    if (loadingRef.current) return
    if (!reset && requestedPagesRef.current.has(targetPage)) return
    if (reset) requestedPagesRef.current.clear()
    requestedPagesRef.current.add(targetPage)
    loadingRef.current = true
    setLoading(true)
    setError('')
    try {
      const response = await api.homeFeed(targetPage, pageSize)
      setTotal(response.total)
      setPage(targetPage + 1)
      setLoadedOnce(true)
      if (response.records.length === 0) setExhausted(true)
      setImages((current) => {
        const base = reset ? [] : current
        const seen = new Set(base.map((image) => image.id))
        return [...base, ...response.records.filter((image) => !seen.has(image.id))]
      })
    } catch (reason) {
      requestedPagesRef.current.delete(targetPage)
      setLoadedOnce(true)
      setError(reason instanceof Error ? reason.message : '图片流加载失败')
    } finally {
      loadingRef.current = false
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadPage(1, true)
  }, [loadPage])

  useEffect(() => {
    const target = sentinelRef.current
    if (!target) return
    const observer = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting) && hasMore && !loadingRef.current) void loadPage(page)
    }, { rootMargin: '560px 0px' })
    observer.observe(target)
    return () => observer.disconnect()
  }, [hasMore, loadPage, page])

  async function openImage(image: ImageView) {
    await api.trackImageClick(image.id, 'home', images.findIndex((item) => item.id === image.id) + 1).catch(() => undefined)
    navigate(`/image/${image.id}`)
  }

  function reloadFeed() {
    requestedPagesRef.current.clear()
    setImages([])
    setTotal(0)
    setPage(1)
    setLoadedOnce(false)
    setExhausted(false)
    void loadPage(1, true)
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  return (
    <div className="feed-page">
      <main className="feed-page__main">
        <MasonryGrid posts={images} loading={loading && images.length === 0} emptyLabel={loading ? '正在加载图片...' : '还没有图片'} onOpen={openImage} />
        {error && (
          <div className="feed-page__state">
            <span>{error}</span>
            <button type="button" onClick={reloadFeed}><RefreshCw size={15} />重新加载</button>
          </div>
        )}
        <div ref={sentinelRef} className="feed-page__sentinel" />
        {loading && images.length > 0 && <div className="feed-page__loading"><span /><span /><span /></div>}
        {!loading && images.length > 0 && !hasMore && <p className="feed-page__ending">已经到底了</p>}
      </main>
    </div>
  )
}
