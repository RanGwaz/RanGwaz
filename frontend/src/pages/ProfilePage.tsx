/** User profile page with editable identity and a shared masonry grid. */
import { Check, Edit3, Loader2, LogOut, Plus, UserPlus, X } from 'lucide-react'
import { FormEvent, useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useAuth } from '../AuthContext'
import { MasonryGrid } from '../components/MasonryGrid'
import { api } from '../services/api'
import type { PostView, UserStats, UserSummary } from '../types'
import { avatarUrl, countText } from '../utils/format'

interface ProfileDraft {
  avatarUrl: string
  backgroundUrl: string
  bio: string
  nickname: string
}

/** Create editable profile fields from a summary. */
function toDraft(profile: UserSummary): ProfileDraft {
  return {
    avatarUrl: profile.avatarUrl || '',
    backgroundUrl: profile.backgroundUrl || '',
    bio: profile.bio || '',
    nickname: profile.nickname || '',
  }
}

export function ProfilePage() {
  const { id } = useParams()
  const auth = useAuth()
  const navigate = useNavigate()
  const targetId = useMemo(() => Number(id || auth.user?.id || 0), [auth.user?.id, id])
  const isOwnProfile = Boolean(auth.user && targetId === auth.user.id)
  const [profile, setProfile] = useState<UserSummary | null>(null)
  const [stats, setStats] = useState<UserStats | null>(null)
  const [posts, setPosts] = useState<PostView[]>([])
  const [draft, setDraft] = useState<ProfileDraft | null>(null)
  const [editing, setEditing] = useState(false)
  const [following, setFollowing] = useState(false)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!auth.ready) return
    if (!targetId) {
      setLoading(false)
      auth.openAuth()
      return
    }
    setLoading(true)
    setError('')
    Promise.all([api.profile(targetId), api.userStats(targetId), api.userPosts(targetId, 60)]).then(([user, userStats, userPosts]) => {
      setProfile(user)
      setDraft(toDraft(user))
      setStats(userStats)
      setPosts(userPosts)
      if (auth.user && auth.user.id !== targetId) {
        api.followStatus(targetId).then((status) => setFollowing(status.following)).catch(() => undefined)
      }
    }).catch((reason) => setError(reason instanceof Error ? reason.message : '主页加载失败')).finally(() => setLoading(false))
  }, [auth.ready, auth.user?.id, targetId])

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

  async function saveProfile(event: FormEvent) {
    event.preventDefault()
    if (!draft) return
    if (!draft.nickname.trim()) {
      setError('昵称不能为空')
      return
    }
    setSaving(true)
    setError('')
    try {
      const updated = await api.updateProfile({
        avatarUrl: draft.avatarUrl.trim(),
        backgroundUrl: draft.backgroundUrl.trim(),
        bio: draft.bio.trim(),
        nickname: draft.nickname.trim(),
      })
      setProfile(updated)
      auth.updateUser(updated)
      setEditing(false)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '保存失败')
    } finally {
      setSaving(false)
    }
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
        <img className="profile-page__cover" src={profile.backgroundUrl || 'https://picsum.photos/seed/profile-cover/1200/360'} alt="" />
        <div className="profile-page__identity">
          <img className="profile-page__avatar" src={avatarUrl(profile.avatarUrl)} alt="" />
          <section>
            <h1>{profile.nickname}</h1>
            <p>@{profile.username}</p>
            <small>{profile.bio || '用图片记录今天的灵感'}</small>
          </section>
          <nav>
            <strong>{countText(stats?.postCount)}<small>笔记</small></strong>
            <strong>{countText(stats?.followingCount)}<small>关注</small></strong>
            <strong>{countText(stats?.followerCount)}<small>粉丝</small></strong>
          </nav>
          <div className="profile-page__actions">
            {isOwnProfile ? (
              <>
                <button type="button" onClick={() => setEditing(true)}><Edit3 size={16} />编辑资料</button>
                <button type="button" onClick={() => navigate('/publish')}><Plus size={16} />发布</button>
                <button type="button" onClick={() => void auth.logout()}><LogOut size={16} />退出</button>
              </>
            ) : <button type="button" className={following ? 'is-following' : 'is-primary'} onClick={toggleFollow}><UserPlus size={16} />{following ? '已关注' : '关注'}</button>}
          </div>
        </div>
        {editing && draft && (
          <form className="profile-page__editor" onSubmit={saveProfile}>
            <div>
              <label>昵称<input value={draft.nickname} maxLength={24} onChange={(event) => setDraft({ ...draft, nickname: event.target.value })} /></label>
              <label>头像链接<input value={draft.avatarUrl} onChange={(event) => setDraft({ ...draft, avatarUrl: event.target.value })} placeholder="https://..." /></label>
              <label>封面链接<input value={draft.backgroundUrl} onChange={(event) => setDraft({ ...draft, backgroundUrl: event.target.value })} placeholder="https://..." /></label>
              <label>简介<textarea value={draft.bio} maxLength={120} onChange={(event) => setDraft({ ...draft, bio: event.target.value })} placeholder="介绍一下自己" /></label>
            </div>
            {error && <p>{error}</p>}
            <footer>
              <button type="button" onClick={() => { setEditing(false); setDraft(toDraft(profile)) }}><X size={16} />取消</button>
              <button className="is-primary" type="submit" disabled={saving}>{saving ? <Loader2 size={16} /> : <Check size={16} />}保存</button>
            </footer>
          </form>
        )}
      </header>
      <main className="profile-page__body">
        <div className="profile-page__tabs">
          <button className="is-active" type="button">作品</button>
          <button type="button">收藏</button>
          <button type="button">喜欢</button>
        </div>
        <MasonryGrid posts={posts} emptyLabel={isOwnProfile ? '发布第一张图片，开始你的主页' : '这个用户还没有发布内容'} onOpen={(target) => navigate(`/posts/${target.id}`)} />
      </main>
    </div>
  )
}
