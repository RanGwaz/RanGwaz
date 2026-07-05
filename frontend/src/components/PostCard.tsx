/** Masonry feed card for image posts. */
import { Heart } from 'lucide-react'
import { KeyboardEvent, MouseEvent, useEffect, useState } from 'react'
import { useAuth } from '../AuthContext'
import { api } from '../services/api'
import type { ImageView } from '../types'
import { aspectRatio, countText, imageThumbnail, preloadImageOriginal } from '../utils/format'

interface PostCardProps {
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
  if (status === 'PENDING_REVIEW') return '检测中'
  if (status === 'REJECTED') return '检测未通过'
  return '检测中'
}

function reviewTone(status?: string) {
  return status === 'REJECTED' ? 'is-rejected' : 'is-pending'
}

export function PostCard({ post, onLikeChange, onOpen }: PostCardProps) {
  const auth = useAuth()
  const title = cleanCardTitle(post.title)
  const publicPost = isPublicPost(post)
  const [liked, setLiked] = useState(Boolean(post.likedByMe))
  const [likeCount, setLikeCount] = useState(post.likeCount)
  const [likeBusy, setLikeBusy] = useState(false)

  useEffect(() => {
    setLiked(Boolean(post.likedByMe))
    setLikeCount(post.likeCount)
    setLikeBusy(false)
  }, [post.id, post.likedByMe, post.likeCount])

  useEffect(() => {
    if (!auth.user) {
      setLiked(false)
      return
    }
    let cancelled = false
    api.interactionStatus(post.id).then((status) => {
      if (!cancelled) setLiked(status.liked)
    }).catch(() => undefined)
    return () => {
      cancelled = true
    }
  }, [auth.user?.id, post.id])

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
      className={publicPost ? 'feed-card' : 'feed-card feed-card--review'}
      tabIndex={0}
      onClick={openCard}
      onFocus={warmDetailImage}
      onKeyDown={handleKeyDown}
      onPointerDown={warmDetailImage}
      onPointerEnter={warmDetailImage}
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
        ) : <span className="feed-card__review-text">{post.reviewReason || '安全检测通过后公开展示'}</span>}
      </footer>
    </article>
  )
}
