/** User profile page with editable identity and a shared masonry grid. */
import {
  BadgeCheck,
  BarChart3,
  Edit3,
  Grid2X2,
  Heart,
  Images,
  Link as LinkIcon,
  List,
  Loader2,
  LogOut,
  MapPin,
  MessageCircle,
  MoreHorizontal,
  UserPlus,
  X,
} from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useAuth } from '../AuthContext'
import { MasonryGrid } from '../components/MasonryGrid'
import { api } from '../services/api'
import type { ImageView, UserStats, UserSummary } from '../types'
import { avatarUrl, countText, imageThumbnail } from '../utils/format'

const DEFAULT_PROFILE_BACKGROUND = '/default-background.jpg'
const PROFILE_LOCATION = '中国'

type LayoutMode = 'grid' | 'list'
type ProfileTab = 'works' | 'collections' | 'likes'
type SocialListKind = 'followers' | 'following'

interface SocialDialog {
  error?: string
  kind: SocialListKind
  loading: boolean
  users: UserSummary[]
}

function cleanDisplayText(value?: string | null) {
  const text = value?.trim() || ''
  if (!text) return ''
  if (/^[a-f0-9]{16,}$/i.test(text)) return ''
  if (/^imported image$/i.test(text)) return ''
  if (text === '未命名图片') return ''
  return text
}

function imageTitle(image: ImageView) {
  return cleanDisplayText(image.title)
}

function isPublicImage(image: ImageView) {
  return !image.status || image.status === 'PUBLISHED'
}

function reviewLabel(status?: string) {
  if (status === 'PENDING_REVIEW') return '待处理'
  if (status === 'REJECTED') return '未通过'
  if (status === 'PUBLISHED' || status === 'APPROVED') return '已通过'
  if (status === 'SUPERSEDED') return '已替换'
  return '待处理'
}

function reviewTone(status?: string) {
  if (status === 'REJECTED') return 'is-rejected'
  if (status === 'PUBLISHED' || status === 'APPROVED') return 'is-approved'
  return 'is-pending'
}

function collectTags(images: ImageView[]) {
  const map = new Map<string, number>()
  images.forEach((image) => {
    image.tags?.forEach((tag) => {
      const name = tag.trim()
      if (!name) return
      map.set(name, (map.get(name) || 0) + 1)
    })
    image.assets?.forEach((asset) => {
      asset.metadata?.tags?.forEach((tag) => {
        const name = tag.name.trim()
        if (!name) return
        map.set(name, (map.get(name) || 0) + 1)
      })
    })
  })
  return Array.from(map.entries())
    .map(([name, count]) => ({ count, name }))
    .sort((left, right) => right.count - left.count || left.name.localeCompare(right.name, 'zh-CN'))
    .slice(0, 18)
}

export function ProfilePage() {
  const { id } = useParams()
  const auth = useAuth()
  const navigate = useNavigate()
  const targetId = useMemo(() => Number(id || auth.user?.id || 0), [auth.user?.id, id])
  const isOwnProfile = Boolean(auth.user && targetId === auth.user.id)
  const [profile, setProfile] = useState<UserSummary | null>(null)
  const [stats, setStats] = useState<UserStats | null>(null)
  const [images, setImages] = useState<ImageView[]>([])
  const [likedImages, setLikedImages] = useState<ImageView[]>([])
  const [favoriteImages, setFavoriteImages] = useState<ImageView[]>([])
  const [following, setFollowing] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [activeTab, setActiveTab] = useState<ProfileTab>('works')
  const [layoutMode, setLayoutMode] = useState<LayoutMode>('grid')
  const [clientIp, setClientIp] = useState('')
  const [socialDialog, setSocialDialog] = useState<SocialDialog | null>(null)
  const [likedLoadedFor, setLikedLoadedFor] = useState<number | null>(null)
  const [favoritesLoadedFor, setFavoritesLoadedFor] = useState<number | null>(null)
  const [galleryLoading, setGalleryLoading] = useState(false)

  const topTags = useMemo(() => collectTags(images), [images])
  const workCount = stats?.imageCount ?? images.length
  const totalLikes = stats?.likedCount ?? likedImages.length
  const totalFavorites = stats?.favoriteCount ?? favoriteImages.length
  const displayBackgroundUrl = profile?.backgroundUrl || DEFAULT_PROFILE_BACKGROUND
  const recentLiked = useMemo(() => likedImages.slice(0, 3), [likedImages])
  const displayImages = useMemo(() => {
    if (activeTab === 'likes') return likedImages
    if (activeTab === 'collections') return favoriteImages
    return [...images].sort((left, right) => new Date(right.createdAt).getTime() - new Date(left.createdAt).getTime())
  }, [activeTab, favoriteImages, images, likedImages])

  useEffect(() => {
    api.clientIp().then((response) => setClientIp(response.ip)).catch(() => undefined)
  }, [])

  useEffect(() => {
    if (!auth.ready) return
    if (!targetId) {
      setLoading(false)
      auth.openAuth()
      return
    }
    setLoading(true)
    setError('')
    setSocialDialog(null)
    setLikedImages([])
    setFavoriteImages([])
    setLikedLoadedFor(null)
    setFavoritesLoadedFor(null)
    Promise.all([
      api.profile(targetId),
      api.userStats(targetId),
      api.userImages(targetId, 60),
    ]).then(([user, userStats, userImages]) => {
      setProfile(user)
      setStats(userStats)
      setImages(userImages)
      if (auth.user && userImages.length > 0) {
        void api.interactionStatuses(userImages.map((image) => image.id)).then((states) => {
          setImages((current) => current.map((image) => {
            const state = states[String(image.id)]
            return state ? { ...image, likedByMe: state.liked } : image
          }))
        }).catch(() => undefined)
      }
      if (auth.user && auth.user.id !== targetId) {
        api.followStatus(targetId).then((status) => setFollowing(status.following)).catch(() => undefined)
      }
    }).catch((reason) => setError(reason instanceof Error ? reason.message : '主页加载失败')).finally(() => setLoading(false))
  }, [auth.ready, auth.user?.id, isOwnProfile, targetId])

  useEffect(() => {
    if (!targetId || activeTab === 'works') return
    const likesTab = activeTab === 'likes'
    if (likesTab ? likedLoadedFor === targetId : favoritesLoadedFor === targetId) return
    setGalleryLoading(true)
    const request = likesTab
      ? api.userLikedImages(targetId, 100)
      : api.userFavoriteImages(targetId, 100)
    request.then((records) => {
      if (likesTab) {
        setLikedImages(records.map((image) => (auth.user?.id === targetId ? { ...image, likedByMe: true } : image)))
        setLikedLoadedFor(targetId)
      } else {
        setFavoriteImages(records)
        setFavoritesLoadedFor(targetId)
      }
    }).catch((reason) => {
      setError(reason instanceof Error ? reason.message : '\u5217\u8868\u52a0\u8f7d\u5931\u8d25')
    }).finally(() => setGalleryLoading(false))
  }, [activeTab, auth.user?.id, favoritesLoadedFor, likedLoadedFor, targetId])


  async function toggleFollow() {
    if (!profile) return
    if (!auth.user) {
      auth.openAuth()
      return
    }
    if (following) await api.unfollow(profile.id)
    else await api.follow(profile.id, 'profile')
    setFollowing(!following)
    setStats((current) => current ? { ...current, followerCount: Math.max(0, current.followerCount + (following ? -1 : 1)) } : current)
  }

  async function logoutAndGoHome() {
    await auth.logout()
    navigate('/home', { replace: true })
  }

  function openImage(target: ImageView) {
    if (!isPublicImage(target)) return
    navigate(`/image/${target.id}`, { state: { previewImage: target } })
    void api.trackImageClick(target.id, isOwnProfile ? 'profile-own' : 'profile').catch(() => undefined)
  }

  function syncLikeChange(post: ImageView, liked: boolean, likeCount: number) {
    const wasLiked = likedImages.some((image) => image.id === post.id)
    const updatedPost = { ...post, likeCount, likedByMe: liked }
    setImages((current) => current.map((image) => (image.id === post.id ? { ...image, likeCount, likedByMe: liked } : image)))
    setLikedImages((current) => {
      const withoutPost = current.filter((image) => image.id !== post.id)
      return liked ? [updatedPost, ...withoutPost] : withoutPost
    })
    if (liked !== wasLiked) {
      setStats((current) => current ? { ...current, likedCount: Math.max(0, current.likedCount + (liked ? 1 : -1)) } : current)
    }
  }

  async function openSocialList(kind: SocialListKind) {
    setSocialDialog({ kind, loading: true, users: [] })
    try {
      const users = kind === 'followers'
        ? await api.userFollowers(targetId, 80)
        : await api.userFollowing(targetId, 80)
      setSocialDialog((current) => current?.kind === kind ? { ...current, loading: false, users } : current)
    } catch (reason) {
      setSocialDialog((current) => current?.kind === kind
        ? { ...current, loading: false, error: reason instanceof Error ? reason.message : '列表加载失败' }
        : current)
    }
  }

  function openUserProfile(user: UserSummary) {
    setSocialDialog(null)
    navigate(auth.user?.id === user.id ? '/profile' : `/profile/${user.id}`)
  }

  function renderGallery() {
    const emptyLabel = activeTab === 'likes'
      ? (isOwnProfile ? '点赞喜欢的作品后，会在这里显示。' : '这个用户还没有公开喜欢记录。')
      : activeTab === 'collections'
        ? (isOwnProfile ? '收藏作品后，会在这里显示。' : '这个用户还没有公开收藏。')
        : (isOwnProfile ? '发布第一张图片，开始你的主页。' : '这个用户还没有发布内容。')

    if (layoutMode === 'list') {
      return (
        <section className="profile-page__list">
          {displayImages.length ? displayImages.map((image) => {
            const title = imageTitle(image)
            return (
              <button
                key={image.id}
                className={!isPublicImage(image) ? 'profile-page__list-card is-under-review' : 'profile-page__list-card'}
                type="button"
                onClick={() => openImage(image)}
              >
                <img src={imageThumbnail(image)} alt="" />
                <span>
                  {title && <strong>{title}</strong>}
                  {!isPublicImage(image)
                    ? <em className={`profile-page__review-pill ${reviewTone(image.status)}`}>{reviewLabel(image.status)}</em>
                    : <small>{countText(image.likeCount + image.favoriteCount)} 喜欢 · {countText(image.commentCount)} 评论</small>}
                  {image.status === 'REJECTED' && image.reviewReason && <small>{image.reviewReason}</small>}
                </span>
              </button>
            )
          }) : <p>{emptyLabel}</p>}
        </section>
      )
    }

    return <MasonryGrid posts={displayImages} loading={loading || galleryLoading} emptyLabel={emptyLabel} onLikeChange={syncLikeChange} onOpen={openImage} />
  }

  if (loading) {
    return (
      <div className="profile-page">
        <section className="profile-page__loading">
          <Loader2 size={20} />
          正在加载主页...
        </section>
      </div>
    )
  }

  if (!profile) {
    return (
      <div className="profile-page">
        <section className="profile-page__empty">
          <strong>{error || '需要登录后查看个人资料'}</strong>
          <button type="button" onClick={auth.openAuth}>登录 / 注册</button>
        </section>
      </div>
    )
  }

  return (
    <div className="profile-page">
      <header className="profile-page__head">
        <div className="profile-page__cover-wrap">
          <img className="profile-page__cover" src={displayBackgroundUrl} alt="" />
        </div>

        <div className="profile-page__identity">
          <div className="profile-page__avatar-wrap">
            <img className="profile-page__avatar" src={avatarUrl(profile.avatarUrl)} alt="" />
          </div>
          <section className="profile-page__bio">
            <div className="profile-page__name-row">
              <h1>{profile.nickname}</h1>
              <BadgeCheck size={19} aria-label="已认证" />
            </div>
            <p className="profile-page__meta">
              <span>@{profile.username}</span>
              <span><MapPin size={13} />{PROFILE_LOCATION}</span>
              {clientIp && <span>IP {clientIp}</span>}
              <span>内容创作者</span>
            </p>
            <small>{profile.bio || '用镜头记录生活的细节与美好。'}</small>
          </section>
          <div className="profile-page__actions">
            {isOwnProfile ? (
              <>
                <button type="button" onClick={() => navigate('/profile/edit')}><Edit3 size={16} />编辑资料</button>
                <button type="button" onClick={() => void logoutAndGoHome()}><LogOut size={16} />退出</button>
              </>
            ) : (
              <>
                <button type="button" className={following ? 'is-following' : 'is-primary'} onClick={toggleFollow}><UserPlus size={16} />{following ? '已关注' : '关注'}</button>
                <button type="button" onClick={() => !auth.user && auth.openAuth()}><MessageCircle size={16} />发消息</button>
                <button className="is-icon" type="button" aria-label="更多"><MoreHorizontal size={18} /></button>
              </>
            )}
          </div>
        </div>

        <nav className="profile-page__stats" aria-label="主页统计">
          <button type="button" onClick={() => void openSocialList('followers')}>
            <span>{countText(stats?.followerCount)}</span>
            <small>粉丝</small>
          </button>
          <button type="button" onClick={() => void openSocialList('following')}>
            <span>{countText(stats?.followingCount)}</span>
            <small>关注</small>
          </button>
        </nav>

        <div className="profile-page__navline">
          <div className="profile-page__tabs" role="tablist" aria-label="主页内容">
            <button className={activeTab === 'works' ? 'is-active' : undefined} type="button" onClick={() => setActiveTab('works')}>作品（{countText(workCount)}）</button>
            <button className={activeTab === 'collections' ? 'is-active' : undefined} type="button" onClick={() => setActiveTab('collections')}>收藏（{countText(totalFavorites)}）</button>
            <button className={activeTab === 'likes' ? 'is-active' : undefined} type="button" onClick={() => setActiveTab('likes')}>喜欢（{countText(totalLikes)}）</button>
          </div>
          <div className="profile-page__tools">
            <button type="button" onClick={() => setActiveTab('works')}><BarChart3 size={14} />最新发布</button>
            <span className="profile-page__layout-toggle" aria-label="视图切换">
              <button className={layoutMode === 'grid' ? 'is-active' : undefined} type="button" onClick={() => setLayoutMode('grid')} aria-label="网格视图"><Grid2X2 size={15} /></button>
              <button className={layoutMode === 'list' ? 'is-active' : undefined} type="button" onClick={() => setLayoutMode('list')} aria-label="列表视图"><List size={15} /></button>
            </span>
          </div>
        </div>
      </header>

      <main className="profile-page__content">
        <section className="profile-page__gallery" aria-label="主页作品">
          {renderGallery()}
        </section>

        <aside className="profile-page__side" aria-label="主页补充信息">
          <section className="profile-page__side-card">
            <h2>关于我</h2>
            <p>{profile.bio || '用镜头记录生活的细节与美好，分享值得收藏的画面。'}</p>
            <ul>
              <li><MapPin size={14} />{PROFILE_LOCATION}</li>
              {clientIp && <li><LinkIcon size={14} />当前 IP {clientIp}</li>}
              <li><Images size={14} />{countText(stats?.imageCount)} 件作品</li>
              <li><LinkIcon size={14} />@{profile.username}</li>
            </ul>
          </section>

          <section className="profile-page__side-card">
            <h2>最近喜欢</h2>
            {recentLiked.length ? (
              <div className="profile-page__recent-list">
                {recentLiked.map((image) => {
                  const title = imageTitle(image)
                  return (
                    <button key={image.id} type="button" onClick={() => openImage(image)}>
                      <img src={imageThumbnail(image)} alt="" />
                      <span>
                        {title && <strong>{title}</strong>}
                        <small><Heart size={12} />{countText(image.likeCount)}</small>
                      </span>
                    </button>
                  )
                })}
              </div>
            ) : <p>还没有可展示的喜欢记录。</p>}
          </section>

          <section className="profile-page__side-card profile-page__side-card--tags">
            <h2>常用标签</h2>
            {topTags.length ? (
              <div>
                {topTags.slice(0, 8).map((tag) => <span key={tag.name}>#{tag.name}</span>)}
              </div>
            ) : <p>发布作品后会在这里自动展示标签。</p>}
          </section>
        </aside>
      </main>

      {socialDialog && (
        <div className="profile-page__social-overlay" role="presentation" onClick={() => setSocialDialog(null)}>
          <section className="profile-page__social-dialog" role="dialog" aria-modal="true" aria-label={socialDialog.kind === 'followers' ? '粉丝列表' : '关注列表'} onClick={(event) => event.stopPropagation()}>
            <header>
              <strong>{socialDialog.kind === 'followers' ? '粉丝' : '关注'}</strong>
              <button type="button" aria-label="关闭" onClick={() => setSocialDialog(null)}><X size={18} /></button>
            </header>
            {socialDialog.loading ? (
              <div className="profile-page__social-state"><Loader2 size={18} />正在加载...</div>
            ) : socialDialog.error ? (
              <div className="profile-page__social-state">{socialDialog.error}</div>
            ) : socialDialog.users.length ? (
              <div className="profile-page__social-list">
                {socialDialog.users.map((user) => (
                  <button key={user.id} type="button" onClick={() => openUserProfile(user)}>
                    <img src={avatarUrl(user.avatarUrl)} alt="" />
                    <span>
                      <strong>{user.nickname}</strong>
                      <small>@{user.username}</small>
                      {user.bio && <em>{user.bio}</em>}
                    </span>
                  </button>
                ))}
              </div>
            ) : (
              <div className="profile-page__social-state">{socialDialog.kind === 'followers' ? '还没有粉丝。' : '还没有关注任何人。'}</div>
            )}
          </section>
        </div>
      )}
    </div>
  )
}
