/** Search page for posts, users, and topics. */
import { Search } from 'lucide-react'
import { FormEvent, useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { PostCard } from '../components/PostCard'
import { api } from '../services/api'
import type { SearchResult } from '../types'
import { avatarUrl, countText } from '../utils/format'

export function SearchPage() {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const [keyword, setKeyword] = useState(params.get('q') || '')
  const [result, setResult] = useState<SearchResult>({ users: [], posts: [], topics: [] })
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    const q = params.get('q') || ''
    setKeyword(q)
    if (!q.trim()) {
      setResult({ users: [], posts: [], topics: [] })
      return
    }
    setLoading(true)
    api.search(q).then(setResult).finally(() => setLoading(false))
  }, [params])

  function submit(event: FormEvent) {
    event.preventDefault()
    if (keyword.trim()) navigate(`/search?q=${encodeURIComponent(keyword.trim())}`)
  }

  return (
    <div className="search-page">
      <header className="search-page__head">
        <form className="search-page__search" onSubmit={submit}>
          <Search size={20} />
          <input value={keyword} onChange={(event) => setKeyword(event.target.value)} placeholder="搜索笔记、用户或标签" />
          <button type="submit">搜索</button>
        </form>
        <p>{keyword.trim() ? `搜索 “${keyword.trim()}”` : '输入关键词发现内容、用户和标签'}</p>
      </header>
      <main className="search-page__body">
        {loading && <section className="search-page__state">正在搜索...</section>}
        {!loading && result.topics.length > 0 && (
          <section className="search-page__section">
            <h2>标签</h2>
            <div className="search-page__topic-row">
              {result.topics.map((topic) => (
                <button key={topic.id} type="button" onClick={() => navigate(`/search?q=${encodeURIComponent(topic.name)}`)}>
                  <strong>#{topic.name}</strong>
                  <span>{countText(topic.postCount)} 篇内容</span>
                </button>
              ))}
            </div>
          </section>
        )}
        {!loading && result.users.length > 0 && (
          <section className="search-page__section">
            <h2>用户</h2>
            <div className="search-page__user-list">
              {result.users.map((user) => (
                <article key={user.id} onClick={() => navigate(`/users/${user.id}`)}>
                  <img src={avatarUrl(user.avatarUrl)} alt="" />
                  <span><strong>{user.nickname}</strong><small>@{user.username}</small></span>
                  <button type="button">主页</button>
                </article>
              ))}
            </div>
          </section>
        )}
        {!loading && result.posts.length > 0 && (
          <section className="search-page__section">
            <h2>笔记</h2>
            <div className="search-page__post-grid">
              {result.posts.map((post) => <PostCard key={post.id} post={post} onOpen={(target) => navigate(`/posts/${target.id}`)} />)}
            </div>
          </section>
        )}
      </main>
    </div>
  )
}
