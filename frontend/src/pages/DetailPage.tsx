/** Pinterest-style post detail page with related masonry feed. */
import { ArrowLeft, ChevronDown, ChevronLeft, ChevronRight, ChevronUp, Heart, MessageCircle, MoreHorizontal, Send } from 'lucide-react'
import { CSSProperties, FormEvent, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useAuth } from '../AuthContext'
import { PostCard } from '../components/PostCard'
import { api } from '../services/api'
import type { CommentView, PostView } from '../types'
import { aspectRatio, avatarUrl, countText, postCover, relativeTime } from '../utils/format'

const DETAIL_BACK_COLUMN_WIDTH = 52
const DETAIL_GRID_GAP = 16
const DETAIL_TARGET_COLUMN_WIDTH = 240
const DETAIL_MAX_COLUMNS = 24
const DETAIL_MAX_PANEL_COLUMNS = 5
const DETAIL_CARD_CHROME_HEIGHT = 82

/** Clamp a number into an inclusive range. */
function clampNumber(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value))
}

/** Resolve Pinterest-like fluid columns from the available detail canvas width. */
function resolveDetailGrid(containerWidth: number) {
  const pinAreaWidth = Math.max(260, containerWidth - DETAIL_BACK_COLUMN_WIDTH - DETAIL_GRID_GAP)
  const totalColumns = clampNumber(
    Math.floor((pinAreaWidth + DETAIL_GRID_GAP) / (DETAIL_TARGET_COLUMN_WIDTH + DETAIL_GRID_GAP)),
    1,
    DETAIL_MAX_COLUMNS,
  )
  const columnWidth = (pinAreaWidth - (totalColumns - 1) * DETAIL_GRID_GAP) / totalColumns
  const maxPanelColumns = totalColumns >= 5 ? Math.min(DETAIL_MAX_PANEL_COLUMNS, totalColumns - 2) : Math.max(1, totalColumns - 1)
  const panelColumns = totalColumns >= 5 ? clampNumber(Math.round(totalColumns * 0.44), 3, maxPanelColumns) : maxPanelColumns
  return { columnWidth, panelColumns, totalColumns }
}

/** Estimate rendered card height for the masonry packer. */
function estimateCardHeight(post: PostView, columnWidth: number) {
  const [w, h] = aspectRatio(post).split('/').map((item) => Number(item.trim()))
  const ratio = Number.isFinite(w) && Number.isFinite(h) && w > 0 ? h / w : 1.35
  return Math.max(136, columnWidth * ratio) + DETAIL_CARD_CHROME_HEIGHT
}

/** Pack related posts into shortest columns, reserving only the detail panel columns. */
function layoutRelatedPosts(posts: PostView[], count: number, reservedColumns: number, panelHeight: number, columnWidth: number) {
  const safeCount = Math.max(1, count)
  const reservedHeight = panelHeight > 0 ? panelHeight + DETAIL_GRID_GAP : 0
  const heights = Array.from({ length: safeCount }, (_, index) => (index < reservedColumns ? reservedHeight : 0))
  const items = posts.map((post) => {
    const cardHeight = estimateCardHeight(post, columnWidth)
    const columnIndex = heights.reduce((minIndex, height, index) => (height < heights[minIndex] ? index : minIndex), 0)
    const x = columnIndex * (columnWidth + DETAIL_GRID_GAP)
    const y = heights[columnIndex]
    heights[columnIndex] += cardHeight + DETAIL_GRID_GAP
    return { height: cardHeight, post, width: columnWidth, x, y }
  })
  const height = Math.max(...heights, 1)
  return { height, items }
}

export function DetailPage() {
  const { id } = useParams()
  const postId = Number(id)
  const [post, setPost] = useState<PostView | null>(null)
  const [comments, setComments] = useState<CommentView[]>([])
  const [related, setRelated] = useState<PostView[]>([])
  const [liked, setLiked] = useState(false)
  const [favorited, setFavorited] = useState(false)
  const [following, setFollowing] = useState(false)
  const [draft, setDraft] = useState('')
  const [activeAsset, setActiveAsset] = useState(0)
  const [commentsOpen, setCommentsOpen] = useState(false)
  const [loading, setLoading] = useState(false)
  const [relatedPage, setRelatedPage] = useState(1)
  const [relatedTotal, setRelatedTotal] = useState(0)
  const [relatedColumns, setRelatedColumns] = useState(6)
  const [reservedColumns, setReservedColumns] = useState(3)
  const [columnWidth, setColumnWidth] = useState(260)
  const [gridReady, setGridReady] = useState(false)
  const [panelHeight, setPanelHeight] = useState(0)
  const [lightbox, setLightbox] = useState(false)
  const mainRef = useRef<HTMLElement | null>(null)
  const panelRef = useRef<HTMLElement | null>(null)
  const sentinelRef = useRef<HTMLDivElement | null>(null)
  const navigate = useNavigate()
  const auth = useAuth()

  const relatedLayout = useMemo(
    () => layoutRelatedPosts(related, relatedColumns, reservedColumns, panelHeight, columnWidth),
    [related, relatedColumns, reservedColumns, panelHeight, columnWidth],
  )
  const hasMoreRelated = related.length < relatedTotal || relatedTotal === 0
  const relatedReady = gridReady && panelHeight > 0 && related.length > 0

  useLayoutEffect(() => {
    window.scrollTo({ top: 0, left: 0, behavior: 'auto' })
  }, [postId])

  useEffect(() => {
    if (!Number.isFinite(postId) || postId <= 0) return
    setLoading(true)
    setPost(null)
    setComments([])
    setRelated([])
    setRelatedPage(1)
    setActiveAsset(0)
    setCommentsOpen(false)
    setGridReady(false)
    setPanelHeight(0)
    Promise.all([
      api.postDetail(postId),
      api.commentsPage(postId, 1, 12),
      api.similarPosts(postId, 1, 36),
    ]).then(([detail, commentPage, relatedPageData]) => {
      setPost(detail)
      setComments(commentPage.records)
      setRelated(relatedPageData.records)
      setRelatedTotal(relatedPageData.total)
      setRelatedPage(2)
    }).finally(() => setLoading(false))
  }, [postId])

  useEffect(() => {
    if (!auth.user || !post) {
      setLiked(false)
      setFavorited(false)
      setFollowing(false)
      return
    }
    api.interactionStatus(post.id).then((status) => {
      setLiked(status.liked)
      setFavorited(status.favorited)
    }).catch(() => undefined)
    api.followStatus(post.author.id).then((status) => setFollowing(status.following)).catch(() => undefined)
  }, [auth.user, post])

  useLayoutEffect(() => {
    const target = mainRef.current
    if (!target) return
    let frame = 0
    const update = () => {
      cancelAnimationFrame(frame)
      frame = requestAnimationFrame(() => {
        if (!target.clientWidth) return
        const grid = resolveDetailGrid(target.clientWidth)
        setRelatedColumns(grid.totalColumns)
        setReservedColumns(grid.panelColumns)
        setColumnWidth(grid.columnWidth)
        setGridReady(true)
      })
    }
    update()
    const observer = new ResizeObserver(update)
    observer.observe(target)
    window.addEventListener('resize', update)
    return () => {
      cancelAnimationFrame(frame)
      observer.disconnect()
      window.removeEventListener('resize', update)
    }
  }, [post?.id])

  useLayoutEffect(() => {
    const target = panelRef.current
    if (!target) return
    const update = () => {
      const height = target.offsetHeight
      setPanelHeight(height)
    }
    update()
    const observer = new ResizeObserver(update)
    observer.observe(target)
    return () => observer.disconnect()
  }, [post, commentsOpen])

  useLayoutEffect(() => {
    setPanelHeight(0)
  }, [postId])

  useEffect(() => {
    const target = sentinelRef.current
    if (!target || !post || !hasMoreRelated) return
    const observer = new IntersectionObserver((entries) => {
      if (!entries.some((entry) => entry.isIntersecting)) return
      api.similarPosts(post.id, relatedPage, 36).then((page) => {
        setRelated((current) => [...current, ...page.records.filter((item) => !current.some((known) => known.id === item.id))])
        setRelatedTotal(page.total)
        setRelatedPage((value) => value + 1)
      }).catch(() => undefined)
    }, { rootMargin: '1200px 0px' })
    observer.observe(target)
    return () => observer.disconnect()
  }, [hasMoreRelated, post, relatedPage])

  async function toggleLike() {
    if (!post) return
    if (!auth.user) {
      auth.openAuth()
      return
    }
    const result = await api.toggleLike(post.id)
    setLiked(result.active)
    setPost({ ...post, likeCount: Math.max(0, post.likeCount + (result.active ? 1 : -1)) })
  }

  async function toggleFavorite() {
    if (!post) return
    if (!auth.user) {
      auth.openAuth()
      return
    }
    const result = await api.toggleFavorite(post.id)
    setFavorited(result.active)
    setPost({ ...post, favoriteCount: Math.max(0, post.favoriteCount + (result.active ? 1 : -1)) })
  }

  async function toggleFollow() {
    if (!post) return
    if (!auth.user) {
      auth.openAuth()
      return
    }
    if (following) await api.unfollow(post.author.id)
    else await api.follow(post.author.id, 'detail')
    setFollowing(!following)
  }

  async function submitComment(event: FormEvent) {
    event.preventDefault()
    if (!post || !draft.trim()) return
    if (!auth.user) {
      auth.openAuth()
      return
    }
    const created = await api.comment(post.id, draft.trim())
    setDraft('')
    setCommentsOpen(true)
    setComments((current) => [created, ...current])
    setPost({ ...post, commentCount: post.commentCount + 1 })
  }

  function nextAsset(delta: number) {
    if (!post?.assets?.length) return
    setActiveAsset((value) => (value + delta + post.assets.length) % post.assets.length)
  }

  function openRelated(target: PostView) {
    void api.trackPostClick(target.id, 'similar').catch(() => undefined)
    navigate(`/posts/${target.id}`)
  }

  if (loading || !post || post.id !== postId) {
    return (
      <div className="detail-page">
        <main className="detail-page__loading">
          <span />
          <section><i /><b /><b /><em /></section>
          <section><i /><b /><b /><em /></section>
          <section><i /><b /><b /><em /></section>
        </main>
      </div>
    )
  }

  return (
    <div className="detail-page">
      <main
        ref={mainRef}
        className="detail-page__main"
        style={{
          '--detail-columns': relatedColumns,
          '--detail-reserved-columns': reservedColumns,
          '--detail-column-width': `${columnWidth}px`,
        } as CSSProperties}
      >
        <button className="detail-page__back-btn" type="button" onClick={() => navigate(-1)} aria-label="返回"><ArrowLeft size={24} /></button>
        <section className="detail-page__focus">
          <article className="detail-panel" ref={panelRef}>
            <div className="detail-panel__toolbar">
              <div>
                <button type="button" className={liked ? 'is-active' : ''} onClick={toggleLike}><Heart size={24} /><strong>{countText(post.likeCount)}</strong></button>
                <button type="button"><MessageCircle size={22} /></button>
                <button type="button" onClick={() => api.trackPostShare(post.id)}><Send size={22} /></button>
                <button type="button"><MoreHorizontal size={22} /></button>
              </div>
              <div>
                <button type="button" onClick={() => navigate(`/users/${post.author.id}`)}>个人资料</button>
                <button className={favorited ? 'is-active save' : 'save'} type="button" onClick={toggleFavorite}>保存</button>
              </div>
            </div>
            <div className="detail-panel__media">
              <button className="detail-panel__image-frame" type="button" onClick={() => setLightbox(true)} aria-label="查看大图">
                <img src={postCover(post, activeAsset)} alt={post.title} style={{ aspectRatio: aspectRatio(post) }} />
              </button>
              {post.assets.length > 1 && (
                <>
                  <button className="detail-panel__arrow is-left" type="button" onClick={() => nextAsset(-1)}><ChevronLeft size={22} /></button>
                  <button className="detail-panel__arrow is-right" type="button" onClick={() => nextAsset(1)}><ChevronRight size={22} /></button>
                </>
              )}
            </div>
            <section className="detail-panel__meta">
              <header className="detail-panel__author">
                <button type="button" onClick={() => navigate(`/users/${post.author.id}`)}>
                  <img src={avatarUrl(post.author.avatarUrl)} alt="" />
                  <span><strong>{post.author.nickname}</strong><small>@{post.author.username} · {relativeTime(post.createdAt)}</small></span>
                </button>
                {auth.user?.id !== post.author.id && <button type="button" className={following ? 'is-following' : ''} onClick={toggleFollow}>{following ? '已关注' : '+ 关注'}</button>}
              </header>
              <div className="detail-panel__copy">
                <h1>{post.title}</h1>
                {post.content && <p>{post.content}</p>}
                <div>{post.tags.map((tag) => <span key={tag}>#{tag}</span>)}</div>
              </div>
              <section className="detail-panel__comments">
                <button className="detail-panel__comments-toggle" type="button" onClick={() => setCommentsOpen((value) => !value)} aria-expanded={commentsOpen}>
                  <strong>评论 ({post.commentCount})</strong>
                  {commentsOpen ? <ChevronUp size={22} /> : <ChevronDown size={22} />}
                </button>
                {commentsOpen && (
                  <div className="detail-panel__comments-body">
                    <form className="detail-panel__comment-editor" onSubmit={submitComment}>
                      <input value={draft} onChange={(event) => setDraft(event.target.value)} placeholder="说点什么..." />
                      <button type="submit"><Send size={18} /></button>
                    </form>
                    <div className="detail-panel__comments-list">
                      {comments.map((comment) => (
                        <article key={comment.id}>
                          <img src={avatarUrl(comment.author.avatarUrl)} alt="" />
                          <span><b>{comment.author.nickname}</b><small>{relativeTime(comment.createdAt)}</small><p>{comment.content}</p></span>
                        </article>
                      ))}
                    </div>
                  </div>
                )}
              </section>
            </section>
          </article>
        </section>
        <section className={relatedReady ? 'detail-related' : 'detail-related is-loading'}>
          {relatedReady ? (
            <div className="detail-related__waterfall" style={{ height: relatedLayout.height } as CSSProperties}>
              {relatedLayout.items.map((item) => (
                <div
                  className="detail-related__item"
                  key={item.post.id}
                  style={{ transform: `translate3d(${item.x}px,${item.y}px,0)`, width: item.width } as CSSProperties}
                >
                  <PostCard post={item.post} onOpen={openRelated} />
                </div>
              ))}
            </div>
          ) : <div className="detail-related__loading" />}
        </section>
        <div ref={sentinelRef} className="detail-related__sentinel" />
      </main>
      {lightbox && <button type="button" className="lightbox" onClick={() => setLightbox(false)}><img src={postCover(post, activeAsset)} alt={post.title} /></button>}
    </div>
  )
}
