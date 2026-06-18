/** Masonry feed card for image posts. */
import { Eye, Heart } from 'lucide-react'
import { KeyboardEvent, MouseEvent, useEffect, useState } from 'react'
import { useAuth } from '../AuthContext'
import { api } from '../services/api'
import type { ImageView } from '../types'
import { aspectRatio, countText, imageThumbnail, preloadImageOriginal } from '../utils/format'

interface PostCardProps {
  post: ImageView
  onOpen: (post: ImageView) => void
}

export function PostCard({ post, onOpen }: PostCardProps) {
  const auth = useAuth()
  const [liked, setLiked] = useState(false)
  const [likeCount, setLikeCount] = useState(post.likeCount)
  const label = post.title || post.content || post.tags?.[0] || ''

  useEffect(() => {
    setLikeCount(post.likeCount)
    setLiked(false)
  }, [post.id, post.likeCount])

  function warmDetailImage() {
    preloadImageOriginal(post)
  }

  function openCard() {
    onOpen(post)
  }

  function handleKeyDown(event: KeyboardEvent<HTMLElement>) {
    if (event.target === event.currentTarget && event.key === 'Enter') openCard()
  }

  async function toggleLike(event: MouseEvent<HTMLButtonElement>) {
    event.stopPropagation()
    if (!auth.user) {
      auth.openAuth()
      return
    }
    const result = await api.toggleLike(post.id)
    setLiked(result.active)
    setLikeCount((current) => Math.max(0, current + (result.active ? 1 : -1)))
  }

  return (
    <article
      className="feed-card"
      tabIndex={0}
      onClick={openCard}
      onFocus={warmDetailImage}
      onKeyDown={handleKeyDown}
      onPointerDown={warmDetailImage}
      onPointerEnter={warmDetailImage}
    >
      <img
        className="feed-card__image"
        src={imageThumbnail(post)}
        alt={label || '图片'}
        style={{ aspectRatio: aspectRatio(post) }}
        loading="lazy"
        decoding="async"
      />
      <span className="feed-card__shade" aria-hidden="true" />
      {label && (
        <div className="feed-card__meta">
          <strong>{label}</strong>
          {post.tags?.[0] && <span>#{post.tags[0]}</span>}
        </div>
      )}
      <div className="feed-card__hoverbar">
        <button
          className={liked ? 'feed-card__metric feed-card__metric--like is-active' : 'feed-card__metric feed-card__metric--like'}
          type="button"
          onClick={toggleLike}
          aria-label="点赞"
        >
          <Heart size={15} />
          <strong>{countText(likeCount)}</strong>
        </button>
        <span className="feed-card__metric" aria-label={`浏览量 ${countText(post.viewCount)}`}>
          <Eye size={15} />
          <strong>{countText(post.viewCount)}</strong>
        </span>
      </div>
    </article>
  )
}
