/** Masonry feed card for image posts. */
import { Check, Eye, Heart, UserPlus } from 'lucide-react'
import { KeyboardEvent, MouseEvent, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../AuthContext'
import { api } from '../services/api'
import type { ImageView } from '../types'
import { aspectRatio, avatarUrl, countText, imageThumbnail, preloadImageOriginal } from '../utils/format'

interface PostCardProps {
  post: ImageView
  onOpen: (post: ImageView) => void
}

export function PostCard({ post, onOpen }: PostCardProps) {
  const auth = useAuth()
  const navigate = useNavigate()
  const [liked, setLiked] = useState(false)
  const [likeCount, setLikeCount] = useState(post.likeCount)
  const [following, setFollowing] = useState<boolean | null>(null)
  const isOwnImage = Boolean(auth.user && auth.user.id === post.author.id)

  useEffect(() => {
    setLikeCount(post.likeCount)
    setLiked(false)
    setFollowing(null)
  }, [post.id, post.likeCount])

  function warmDetailImage() {
    preloadImageOriginal(post)
    if (!auth.user || isOwnImage || following !== null) return
    api.followStatus(post.author.id).then((status) => setFollowing(status.following)).catch(() => undefined)
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

  async function toggleFollow(event: MouseEvent<HTMLButtonElement>) {
    event.stopPropagation()
    if (!auth.user) {
      auth.openAuth()
      return
    }
    if (isOwnImage) {
      navigate('/profile')
      return
    }
    const active = Boolean(following)
    if (active) await api.unfollow(post.author.id)
    else await api.follow(post.author.id, 'card')
    setFollowing(!active)
  }

  function openAuthor(event: MouseEvent<HTMLButtonElement>) {
    event.stopPropagation()
    navigate(`/profile/${post.author.id}`)
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
      <img className="feed-card__image" src={imageThumbnail(post)} alt={post.title || '图片'} style={{ aspectRatio: aspectRatio(post) }} loading="lazy" decoding="async" />
      <span className="feed-card__shade" aria-hidden="true" />
      <div className="feed-card__topline">
        <button className={liked ? 'feed-card__metric feed-card__metric--like is-active' : 'feed-card__metric feed-card__metric--like'} type="button" onClick={toggleLike} aria-label="点赞">
          <Heart size={15} />
          <strong>{countText(likeCount)}</strong>
        </button>
        <span className="feed-card__metric" aria-label={`浏览量 ${countText(post.viewCount)}`}>
          <Eye size={15} />
          <strong>{countText(post.viewCount)}</strong>
        </span>
      </div>
      <div className="feed-card__author">
        <button className="feed-card__author-link" type="button" onClick={openAuthor} aria-label={`查看 ${post.author.nickname} 的主页`}>
          <img src={avatarUrl(post.author.avatarUrl)} alt="" />
          <span>
            <strong>{post.author.nickname}</strong>
            <small>@{post.author.username}</small>
          </span>
        </button>
        <button className={following ? 'feed-card__follow is-following' : 'feed-card__follow'} type="button" onClick={toggleFollow}>
          {isOwnImage ? '主页' : following ? <><Check size={13} />已关注</> : <><UserPlus size={13} />关注</>}
        </button>
      </div>
    </article>
  )
}
