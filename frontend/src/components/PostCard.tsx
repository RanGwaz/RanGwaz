/** Masonry feed card for image posts. */
import type { ImageView } from '../types'
import { aspectRatio, imageThumbnail } from '../utils/format'

interface PostCardProps {
  post: ImageView
  onOpen: (post: ImageView) => void
}

export function PostCard({ post, onOpen }: PostCardProps) {
  return (
    <article className="feed-card" tabIndex={0} onClick={() => onOpen(post)} onKeyDown={(event) => event.key === 'Enter' && onOpen(post)}>
      <img src={imageThumbnail(post)} alt={post.title || '图片'} style={{ aspectRatio: aspectRatio(post) }} loading="lazy" decoding="async" />
    </article>
  )
}
