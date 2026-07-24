/** Masonry feed card for image posts. */
import { Heart } from 'lucide-react'
import { KeyboardEvent, MouseEvent, useEffect, useRef, useState } from 'react'
import { useAuth } from '../AuthContext'
import { api } from '../services/api'
import type { ImageView } from '../types'
import { aspectRatio, countText, imageThumbnail, preloadImageOriginal } from '../utils/format'

interface PostCardProps {
  onImpression?: (post: ImageView) => void
  onLikeChange?: (post: ImageView, liked: boolean, likeCount: number) => void
  post: ImageView
  onOpen: (post: ImageView) => void
}

function cleanCardTitle(value?: string | null) {
  const text = value?.trim() || ''
  if (!text) return ''
  if (/^[a-f0-9]{16,}$/i.test(text)) return ''
  if (/^imported image$/i.test(text)) return ''
  if (text === '未命名图片') return ''
  return text
}

function isPublicPost(post: ImageView) {
  return !post.status || post.status === 'PUBLISHED'
}

function reviewLabel(status?: string) {
  if (status === 'PENDING_REVIEW') return '待处理'
  if (status === 'REJECTED') return '未通过'
  return '待处理'
}

function reviewTone(status?: string) {
  return status === 'REJECTED' ? 'is-rejected' : 'is-pending'
}

export function PostCard({ post, onImpression, onLikeChange, onOpen }: PostCardProps) {
  const auth = useAuth()
  const title = cleanCardTitle(post.title)
  const publicPost = isPublicPost(post)
  const [liked, setLiked] = useState(Boolean(post.likedByMe))
  const [likeCount, setLikeCount] = useState(post.likeCount)
  const [likeBusy, setLikeBusy] = useState(false)
  const cardRef = useRef<HTMLElement | null>(null)
  const impressionTrackedRef = useRef<number | null>(null)

  useEffect(() => {
    setLiked(Boolean(auth.user && post.likedByMe))
    setLikeCount(post.likeCount)
    setLikeBusy(false)
  }, [auth.user?.id, post.id, post.likedByMe, post.likeCount])
  useEffect(() => {
    const target = cardRef.current
    if (!target || !publicPost || !onImpression || impressionTrackedRef.current === post.id) return
    const observer = new IntersectionObserver((entries) => {
      if (!entries.some((entry) => entry.isIntersecting && entry.intersectionRatio >= 0.55)) return
      impressionTrackedRef.current = post.id
      onImpression(post)
      observer.disconnect()
    }, { threshold: [0.55] })
    observer.observe(target)
    return () => observer.disconnect()
  }, [onImpression, post, publicPost])


  // Feed and profile pages hydrate interaction state in one batch request.

  function warmDetailImage() {
    if (!publicPost) return
    preloadImageOriginal(post)
  }

  function openCard() {
    if (!publicPost) return
    onOpen(post)
  }

  function handleKeyDown(event: KeyboardEvent<HTMLElement>) {
    if (event.target === event.currentTarget && event.key === 'Enter') openCard()
  }

  async function toggleLike(event: MouseEvent<HTMLButtonElement>) {
    event.preventDefault()
    event.stopPropagation()
    if (!publicPost) return
    if (!auth.user) {
      auth.openAuth()
      return
    }
    if (likeBusy) return
    setLikeBusy(true)
    try {
      const wasLiked = liked
      const result = await api.toggleLike(post.id)
      const nextLikeCount = Math.max(0, likeCount + (result.active !== wasLiked ? (result.active ? 1 : -1) : 0))
      setLiked(result.active)
      setLikeCount(nextLikeCount)
      onLikeChange?.({ ...post, likeCount: nextLikeCount, likedByMe: result.active }, result.active, nextLikeCount)
    } finally {
      setLikeBusy(false)
    }
  }

  return (
    <article
      ref={cardRef}
      className={publicPost ? 'feed-card' : 'feed-card feed-card--review'}
      tabIndex={0}
      onClick={openCard}
      onKeyDown={handleKeyDown}
      onPointerDown={warmDetailImage}
    >
      <div className="feed-card__media">
        <img
          className="feed-card__image"
          src={imageThumbnail(post)}
          alt={title}
          style={{ aspectRatio: aspectRatio(post) }}
          loading="lazy"
          decoding="async"
        />
        {!publicPost && <span className={`feed-card__review-badge ${reviewTone(post.status)}`}>{reviewLabel(post.status)}</span>}
      </div>
      <footer className="feed-card__body">
        {title && <strong className="feed-card__title" title={title}>{title}</strong>}
        {publicPost ? (
          <button
            className={liked ? 'feed-card__likes is-liked' : 'feed-card__likes'}
            type="button"
            onClick={toggleLike}
            disabled={likeBusy}
            aria-label={liked ? '取消点赞' : '点赞'}
          >
            <Heart size={13} />
            {countText(likeCount)}
          </button>
        ) : <span className="feed-card__review-text">{post.reviewReason || '暂未公开'}</span>}
      </footer>
    </article>
  )
}
