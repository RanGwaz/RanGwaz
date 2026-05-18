/** User profile page with a simple image grid. */
import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useAuth } from '../AuthContext'
import { PostCard } from '../components/PostCard'
import { api } from '../services/api'
import type { PostView, UserStats, UserSummary } from '../types'
import { avatarUrl } from '../utils/format'

export function ProfilePage() {
  const { id } = useParams()
  const auth = useAuth()
  const navigate = useNavigate()
  const targetId = useMemo(() => Number(id || auth.user?.id || 0), [auth.user?.id, id])
  const [profile, setProfile] = useState<UserSummary | null>(null)
  const [stats, setStats] = useState<UserStats | null>(null)
  const [posts, setPosts] = useState<PostView[]>([])

  useEffect(() => {
    if (!targetId) {
      auth.openAuth()
      return
    }
    Promise.all([api.profile(targetId), api.userStats(targetId), api.userPosts(targetId, 60)]).then(([user, userStats, userPosts]) => {
      setProfile(user)
      setStats(userStats)
      setPosts(userPosts)
    }).catch(() => undefined)
  }, [auth, targetId])

  if (!profile) return <div className="profile-page"><section>正在加载主页...</section></div>

  return (
    <div className="profile-page">
      <header className="profile-page__head">
        <img className="profile-page__cover" src={profile.backgroundUrl || 'https://picsum.photos/seed/profile-cover/1200/360'} alt="" />
        <div>
          <img className="profile-page__avatar" src={avatarUrl(profile.avatarUrl)} alt="" />
          <span>
            <h1>{profile.nickname}</h1>
            <p>@{profile.username}</p>
            <small>{profile.bio || '用图片记录今天的灵感'}</small>
          </span>
          <nav>
            <strong>{stats?.postCount ?? 0}<small>笔记</small></strong>
            <strong>{stats?.followingCount ?? 0}<small>关注</small></strong>
            <strong>{stats?.followerCount ?? 0}<small>粉丝</small></strong>
          </nav>
        </div>
      </header>
      <main className="profile-page__grid">
        {posts.map((post) => <PostCard key={post.id} post={post} onOpen={(target) => navigate(`/posts/${target.id}`)} />)}
      </main>
    </div>
  )
}
