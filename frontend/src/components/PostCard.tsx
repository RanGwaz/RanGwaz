/** Masonry feed card for image posts. */
import { Heart, MessageCircle, Send, Star } from 'lucide-react'
import { MouseEvent } from 'react'
import type { PostView } from '../types'
import { aspectRatio, avatarUrl, countText, postCover, relativeTime } from '../utils/format'

interface PostCardProps {
  post: PostView
  onOpen: (post: PostView) => void
  onLike?: (post: PostView) => void
  liked?: boolean
}

export function PostCard({ post, onOpen, onLike, liked }: PostCardProps) {
  function like(event: MouseEvent<HTMLButtonElement>) {
    event.stopPropagation()
    onLike?.(post)
  }

  return (
    <article className="feed-card" tabIndex={0} onClick={() => onOpen(post)} onKeyDown={(event) => event.key === 'Enter' && onOpen(post)}>
      <div className="feed-card__media" style={{ aspectRatio: aspectRatio(post) }}>
        <img src={postCover(post)} alt={post.title || '图片'} loading="lazy" decoding="async" />
      </div>
      <div className="feed-card__body">
        <h2>{post.title || '未命名作品'}</h2>
        <div className="feed-card__meta">
          <img src={avatarUrl(post.author.avatarUrl)} alt="" loading="lazy" />
          <span>{post.author.nickname}</span>
          <small>{relativeTime(post.createdAt)}</small>
        </div>
        <div className="feed-card__actions">
          <button className={liked ? 'is-active' : ''} type="button" onClick={like}><Heart size={15} />{countText(post.likeCount)}</button>
          <span><MessageCircle size={14} />{countText(post.commentCount)}</span>
          <span><Star size={14} />{countText(post.collectCount ?? post.favoriteCount)}</span>
          <span><Send size={14} />{countText(post.shareCount)}</span>
        </div>
      </div>
    </article>
  )
}
