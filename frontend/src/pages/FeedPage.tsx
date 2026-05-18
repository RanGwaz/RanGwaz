/** Home feed page with masonry layout and infinite scroll. */
import { CSSProperties, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../AuthContext'
import { PostCard } from '../components/PostCard'
import { api } from '../services/api'
import type { PostView } from '../types'
import { distributePosts } from '../utils/format'

const pageSize = 30

export function FeedPage() {
  const [posts, setPosts] = useState<PostView[]>([])
  const [page, setPage] = useState(1)
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [columnCount, setColumnCount] = useState(5)
  const [liked, setLiked] = useState<Set<number>>(new Set())
  const shellRef = useRef<HTMLDivElement | null>(null)
  const sentinelRef = useRef<HTMLDivElement | null>(null)
  const navigate = useNavigate()
  const auth = useAuth()

  const hasMore = posts.length < total || total === 0
  const columns = useMemo(() => distributePosts(posts, columnCount), [columnCount, posts])

  const loadPage = useCallback(async (targetPage: number, reset = false) => {
    if (loading) return
    setLoading(true)
    setError('')
    try {
      const response = await api.homeFeed(targetPage, pageSize)
      setTotal(response.total)
      setPage(targetPage + 1)
      setPosts((current) => {
        const base = reset ? [] : current
        const seen = new Set(base.map((post) => post.id))
        return [...base, ...response.records.filter((post) => !seen.has(post.id))]
      })
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '推荐流加载失败')
    } finally {
      setLoading(false)
    }
  }, [loading])

  useEffect(() => {
    void loadPage(1, true)
  }, [])

  useEffect(() => {
    function updateColumns() {
      const width = shellRef.current?.clientWidth || window.innerWidth - 112
      setColumnCount(Math.max(1, Math.min(7, Math.floor((width + 14) / 246))))
    }
    updateColumns()
    const observer = new ResizeObserver(updateColumns)
    if (shellRef.current) observer.observe(shellRef.current)
    window.addEventListener('resize', updateColumns)
    return () => {
      observer.disconnect()
      window.removeEventListener('resize', updateColumns)
    }
  }, [])

  useEffect(() => {
    const target = sentinelRef.current
    if (!target) return
    const observer = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting) && hasMore && !loading) void loadPage(page)
    }, { rootMargin: '1200px 0px' })
    observer.observe(target)
    return () => observer.disconnect()
  }, [hasMore, loadPage, loading, page])

  async function openPost(post: PostView) {
    await api.trackPostClick(post.id, 'home', posts.findIndex((item) => item.id === post.id) + 1).catch(() => undefined)
    navigate(`/posts/${post.id}`)
  }

  async function toggleLike(post: PostView) {
    if (!auth.user) {
      auth.openAuth()
      return
    }
    const result = await api.toggleLike(post.id)
    setLiked((current) => {
      const next = new Set(current)
      if (result.active) next.add(post.id)
      else next.delete(post.id)
      return next
    })
    setPosts((current) => current.map((item) => item.id === post.id ? {
      ...item,
      likeCount: Math.max(0, item.likeCount + (result.active ? 1 : -1)),
    } : item))
  }

  function reloadFeed() {
    setPosts([])
    setTotal(0)
    setPage(1)
    void loadPage(1, true)
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  return (
    <div className="feed-page">
      <main ref={shellRef} className="feed-page__main">
        <section className="feed-page__waterfall" style={{ '--feed-columns': columnCount } as CSSProperties}>
          {columns.map((column, index) => (
            <div className="feed-page__column" key={index}>
              {column.map((post) => <PostCard key={post.id} post={post} liked={liked.has(post.id)} onOpen={openPost} onLike={toggleLike} />)}
            </div>
          ))}
        </section>
        {error && <div className="feed-page__state"><span>{error}</span><button type="button" onClick={reloadFeed}>重新加载</button></div>}
        <div ref={sentinelRef} className="feed-page__sentinel" />
        {loading && <div className="feed-page__loading"><span /><span /><span /></div>}
        {!loading && posts.length > 0 && !hasMore && <p className="feed-page__ending">已经到底了</p>}
      </main>
    </div>
  )
}
