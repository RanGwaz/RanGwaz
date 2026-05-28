/** Image detail page with Pinterest-like panel and related masonry feed. */
import { ArrowLeft, ChevronLeft, ChevronRight, Heart, MessageCircle, MoreHorizontal, Send, Star } from 'lucide-react'
import { CSSProperties, FormEvent, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useAuth } from '../AuthContext'
import { PostCard } from '../components/PostCard'
import { api } from '../services/api'
import type { CommentView, ImageView } from '../types'
import { aspectRatio, avatarUrl, countText, imageOriginal, relativeTime } from '../utils/format'

const DETAIL_BACK_COLUMN_WIDTH = 52
const DETAIL_GRID_GAP = 10
const DETAIL_TARGET_COLUMN_WIDTH = 236
const DETAIL_MAX_COLUMNS = 24
const DETAIL_MAX_PANEL_COLUMNS = 5
const DETAIL_CARD_CHROME_HEIGHT = 0

function clampNumber(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value))
}

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

function estimateCardHeight(image: ImageView, columnWidth: number) {
  const [w, h] = aspectRatio(image).split('/').map((item) => Number(item.trim()))
  const ratio = Number.isFinite(w) && Number.isFinite(h) && w > 0 ? h / w : 1.35
  return Math.max(136, columnWidth * ratio) + DETAIL_CARD_CHROME_HEIGHT
}

function layoutRelatedImages(images: ImageView[], count: number, reservedColumns: number, panelHeight: number, columnWidth: number) {
  const safeCount = Math.max(1, count)
  const reservedHeight = panelHeight > 0 ? panelHeight + DETAIL_GRID_GAP : 0
  const heights = Array.from({ length: safeCount }, (_, index) => (index < reservedColumns ? reservedHeight : 0))
  const items = images.map((image) => {
    const cardHeight = estimateCardHeight(image, columnWidth)
    const columnIndex = heights.reduce((minIndex, height, index) => (height < heights[minIndex] ? index : minIndex), 0)
    const x = columnIndex * (columnWidth + DETAIL_GRID_GAP)
    const y = heights[columnIndex]
    heights[columnIndex] += cardHeight + DETAIL_GRID_GAP
    return { height: cardHeight, image, width: columnWidth, x, y }
  })
  return { height: Math.max(...heights, 1), items }
}

function DetailSkeleton() {
  return (
    <div className="detail-page">
      <main className="detail-page__loading">
        <section className="detail-page__loading-panel">
          <i />
          <div>
            <b />
            <b />
            <span />
            <em />
            <b />
            <b />
          </div>
        </section>
        <section className="detail-page__loading-related">
          {Array.from({ length: 12 }, (_, index) => <i key={index} />)}
        </section>
      </main>
    </div>
  )
}

export function DetailPage() {
  const { id } = useParams()
  const imageId = Number(id)
  const [image, setImage] = useState<ImageView | null>(null)
  const [comments, setComments] = useState<CommentView[]>([])
  const [related, setRelated] = useState<ImageView[]>([])
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
    () => layoutRelatedImages(related, relatedColumns, reservedColumns, panelHeight, columnWidth),
    [related, relatedColumns, reservedColumns, panelHeight, columnWidth],
  )
  const hasMoreRelated = related.length < relatedTotal || relatedTotal === 0
  const relatedReady = gridReady && panelHeight > 0 && related.length > 0
  const canShowFollow = !auth.user || auth.user.id !== image?.author.id

  useLayoutEffect(() => {
    window.scrollTo({ top: 0, left: 0, behavior: 'auto' })
  }, [imageId])

  useEffect(() => {
    if (!Number.isFinite(imageId) || imageId <= 0) return
    setLoading(true)
    setImage(null)
    setComments([])
    setRelated([])
    setRelatedPage(1)
    setActiveAsset(0)
    setCommentsOpen(false)
    setGridReady(false)
    setPanelHeight(0)
    Promise.all([
      api.imageDetail(imageId),
      api.commentsPage(imageId, 1, 12),
      api.similarImages(imageId, 1, 36),
    ]).then(([detail, commentPage, relatedPageData]) => {
      setImage(detail)
      setComments(commentPage.records)
      setRelated(relatedPageData.records)
      setRelatedTotal(relatedPageData.total)
      setRelatedPage(2)
    }).finally(() => setLoading(false))
  }, [imageId])

  useEffect(() => {
    if (!auth.user || !image) {
      setLiked(false)
      setFavorited(false)
      setFollowing(false)
      return
    }
    api.interactionStatus(image.id).then((status) => {
      setLiked(status.liked)
      setFavorited(status.favorited)
    }).catch(() => undefined)
    if (auth.user.id !== image.author.id) {
      api.followStatus(image.author.id).then((status) => setFollowing(status.following)).catch(() => undefined)
    } else {
      setFollowing(false)
    }
  }, [auth.user, image])

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
  }, [image?.id])

  useLayoutEffect(() => {
    const target = panelRef.current
    if (!target) return
    const update = () => setPanelHeight(target.offsetHeight)
    update()
    const observer = new ResizeObserver(update)
    observer.observe(target)
    return () => observer.disconnect()
  }, [image, commentsOpen])

  useLayoutEffect(() => {
    setPanelHeight(0)
  }, [imageId])

  useEffect(() => {
    const target = sentinelRef.current
    if (!target || !image || !hasMoreRelated) return
    const observer = new IntersectionObserver((entries) => {
      if (!entries.some((entry) => entry.isIntersecting)) return
      api.similarImages(image.id, relatedPage, 36).then((page) => {
        setRelated((current) => [...current, ...page.records.filter((item) => !current.some((known) => known.id === item.id))])
        setRelatedTotal(page.total)
        setRelatedPage((value) => value + 1)
      }).catch(() => undefined)
    }, { rootMargin: '1100px 0px' })
    observer.observe(target)
    return () => observer.disconnect()
  }, [hasMoreRelated, image, relatedPage])

  async function toggleLike() {
    if (!image) return
    if (!auth.user) {
      auth.openAuth()
      return
    }
    const result = await api.toggleLike(image.id)
    setLiked(result.active)
    setImage({ ...image, likeCount: Math.max(0, image.likeCount + (result.active ? 1 : -1)) })
  }

  async function toggleFavorite() {
    if (!image) return
    if (!auth.user) {
      auth.openAuth()
      return
    }
    const result = await api.toggleFavorite(image.id)
    setFavorited(result.active)
    setImage({ ...image, favoriteCount: Math.max(0, image.favoriteCount + (result.active ? 1 : -1)) })
  }

  async function toggleFollow() {
    if (!image) return
    if (!auth.user) {
      auth.openAuth()
      return
    }
    if (auth.user.id === image.author.id) {
      navigate('/profile')
      return
    }
    if (following) await api.unfollow(image.author.id)
    else await api.follow(image.author.id, 'detail')
    setFollowing(!following)
  }

  async function submitComment(event: FormEvent) {
    event.preventDefault()
    if (!image || !draft.trim()) return
    if (!auth.user) {
      auth.openAuth()
      return
    }
    const created = await api.comment(image.id, draft.trim())
    setDraft('')
    setCommentsOpen(true)
    setComments((current) => [created, ...current])
    setImage({ ...image, commentCount: image.commentCount + 1 })
  }

  function nextAsset(delta: number) {
    if (!image?.assets?.length) return
    setActiveAsset((value) => (value + delta + image.assets.length) % image.assets.length)
  }

  function openRelated(target: ImageView) {
    void api.trackImageClick(target.id, 'similar').catch(() => undefined)
    navigate(`/image/${target.id}`)
  }

  if (loading || !image || image.id !== imageId) return <DetailSkeleton />

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
            <div className="detail-panel__media">
              <button className="detail-panel__image-frame" type="button" onClick={() => setLightbox(true)} aria-label="查看大图">
                <img src={imageOriginal(image, activeAsset)} alt={image.title} style={{ aspectRatio: aspectRatio(image) }} />
              </button>
              {image.assets.length > 1 && (
                <>
                  <button className="detail-panel__arrow is-left" type="button" onClick={() => nextAsset(-1)} aria-label="上一张"><ChevronLeft size={22} /></button>
                  <button className="detail-panel__arrow is-right" type="button" onClick={() => nextAsset(1)} aria-label="下一张"><ChevronRight size={22} /></button>
                </>
              )}
            </div>
            <section className="detail-panel__info">
              <div className="detail-panel__toolbar">
                <div className="detail-panel__tool-group">
                  <button type="button" className={liked ? 'is-active' : ''} onClick={toggleLike} aria-label="点赞"><Heart size={23} /><strong>{countText(image.likeCount)}</strong></button>
                  <button type="button" onClick={() => setCommentsOpen((value) => !value)} aria-label="评论"><MessageCircle size={21} /></button>
                  <button type="button" className={favorited ? 'is-active' : ''} onClick={toggleFavorite} aria-label="收藏"><Star size={21} /></button>
                  <button type="button" onClick={() => api.trackImageShare(image.id)} aria-label="分享"><Send size={21} /></button>
                  <button type="button" aria-label="更多"><MoreHorizontal size={21} /></button>
                </div>
              </div>
              <div className="detail-panel__copy">
                <h1>{image.title}</h1>
                {image.content && <p>{image.content}</p>}
                {image.tags.length > 0 && <div>{image.tags.map((tag) => <span key={tag}>#{tag}</span>)}</div>}
              </div>
              <header className="detail-panel__author">
                <button className="detail-panel__author-card" type="button" onClick={() => navigate(`/profile/${image.author.id}`)}>
                  <img src={avatarUrl(image.author.avatarUrl)} alt="" />
                  <span>
                    <strong>{image.author.nickname}</strong>
                    <small>@{image.author.username} · {relativeTime(image.createdAt)}</small>
                  </span>
                </button>
                <button className={following ? 'detail-panel__follow-btn is-following' : 'detail-panel__follow-btn'} type="button" onClick={toggleFollow}>
                  {canShowFollow ? (following ? '已关注' : '关注') : '个人主页'}
                </button>
              </header>
              <section className="detail-panel__comments">
                <button className="detail-panel__comments-toggle" type="button" onClick={() => setCommentsOpen((value) => !value)} aria-expanded={commentsOpen}>
                  <strong>评论 ({image.commentCount})</strong>
                </button>
                {commentsOpen && (
                  <div className="detail-panel__comments-body">
                    <form className="detail-panel__comment-editor" onSubmit={submitComment}>
                      <input value={draft} onChange={(event) => setDraft(event.target.value)} placeholder="添加评论或展开对话讨论" />
                      <button type="submit" aria-label="发送评论"><Send size={18} /></button>
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
                  key={item.image.id}
                  style={{ transform: `translate3d(${item.x}px,${item.y}px,0)`, width: item.width } as CSSProperties}
                >
                  <PostCard post={item.image} onOpen={openRelated} />
                </div>
              ))}
            </div>
          ) : <div className="detail-related__skeleton">{Array.from({ length: 12 }, (_, index) => <span key={index} />)}</div>}
        </section>
        <div ref={sentinelRef} className="detail-related__sentinel" />
      </main>
      {lightbox && <button type="button" className="lightbox" onClick={() => setLightbox(false)} aria-label="关闭大图"><img src={imageOriginal(image, activeAsset)} alt={image.title} /></button>}
    </div>
  )
}
