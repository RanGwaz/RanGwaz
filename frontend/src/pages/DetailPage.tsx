/** Pinterest-style post detail page with related masonry feed. */
import { ArrowLeft, ChevronLeft, ChevronRight, Heart, MessageCircle, MoreHorizontal, Send, Star } from 'lucide-react'
import { CSSProperties, FormEvent, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useAuth } from '../AuthContext'
import { PostCard } from '../components/PostCard'
import { api } from '../services/api'
import type { CommentView, PostView } from '../types'
import { avatarUrl, countText, distributePosts, postCover, relativeTime } from '../utils/format'

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
  const [loading, setLoading] = useState(false)
  const [relatedPage, setRelatedPage] = useState(1)
  const [relatedTotal, setRelatedTotal] = useState(0)
  const [relatedColumns, setRelatedColumns] = useState(3)
  const [lightbox, setLightbox] = useState(false)
  const sentinelRef = useRef<HTMLDivElement | null>(null)
  const navigate = useNavigate()
  const auth = useAuth()

  const relatedMasonry = useMemo(() => distributePosts(related, relatedColumns), [related, relatedColumns])
  const hasMoreRelated = related.length < relatedTotal || relatedTotal === 0

  useEffect(() => {
    if (!Number.isFinite(postId) || postId <= 0) return
    setLoading(true)
    setPost(null)
    setComments([])
    setRelated([])
    setRelatedPage(1)
    setActiveAsset(0)
    Promise.all([
      api.postDetail(postId),
      api.commentsPage(postId, 1, 12),
      api.similarPosts(postId, 1, 18),
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

  useEffect(() => {
    function update() {
      const width = window.innerWidth
      setRelatedColumns(width >= 1320 ? 3 : width >= 820 ? 2 : 1)
    }
    update()
    window.addEventListener('resize', update)
    return () => window.removeEventListener('resize', update)
  }, [])

  useEffect(() => {
    const target = sentinelRef.current
    if (!target || !post || !hasMoreRelated) return
    const observer = new IntersectionObserver((entries) => {
      if (!entries.some((entry) => entry.isIntersecting)) return
      api.similarPosts(post.id, relatedPage, 18).then((page) => {
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

  if (loading || !post) {
    return <div className="detail-page"><main className="detail-page__state">正在加载详情...</main></div>
  }

  return (
    <div className="detail-page">
      <main className="detail-page__main">
        <section className="detail-page__focus">
          <button className="detail-page__back-btn" type="button" onClick={() => navigate(-1)} aria-label="返回"><ArrowLeft size={24} /></button>
          <article className="detail-panel">
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
              <img src={postCover(post, activeAsset)} alt={post.title} onClick={() => setLightbox(true)} />
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
              <form className="detail-panel__comment-editor" onSubmit={submitComment}>
                <input value={draft} onChange={(event) => setDraft(event.target.value)} placeholder="说点什么..." />
                <button type="submit"><Send size={18} /></button>
              </form>
              <section className="detail-panel__comments">
                <strong>评论 ({post.commentCount})</strong>
                {comments.map((comment) => (
                  <article key={comment.id}>
                    <img src={avatarUrl(comment.author.avatarUrl)} alt="" />
                    <span><b>{comment.author.nickname}</b><small>{relativeTime(comment.createdAt)}</small><p>{comment.content}</p></span>
                  </article>
                ))}
              </section>
            </section>
          </article>
        </section>
        <section className="detail-related">
          <div className="detail-related__waterfall" style={{ '--column-count': relatedColumns } as CSSProperties}>
            {relatedMasonry.map((column, index) => (
              <div className="detail-related__column" key={index}>
                {column.map((item) => <PostCard key={item.id} post={item} onOpen={openRelated} />)}
              </div>
            ))}
          </div>
          <div ref={sentinelRef} className="detail-related__sentinel" />
        </section>
      </main>
      {lightbox && <button type="button" className="lightbox" onClick={() => setLightbox(false)}><img src={postCover(post, activeAsset)} alt={post.title} /></button>}
    </div>
  )
}
