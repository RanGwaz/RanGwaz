/** Search page for images, users, and topics. */
import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { MasonryGrid } from '../components/MasonryGrid'
import { api } from '../services/api'
import type { ImageView, SearchResult, SearchSuggestionItem } from '../types'
import { avatarUrl, countText } from '../utils/format'

export function SearchPage() {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const keyword = params.get('q') || ''
  const [result, setResult] = useState<SearchResult>({ users: [], images: [], topics: [], related: [] })
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const related = result.related ?? []

  useEffect(() => {
    if (!keyword.trim()) {
      setResult({ users: [], images: [], topics: [], related: [] })
      setLoading(false)
      setError('')
      return
    }
    setLoading(true)
    setError('')
    api.search(keyword)
      .then(setResult)
      .catch((reason) => setError(reason instanceof Error ? reason.message : '搜索失败'))
      .finally(() => setLoading(false))
  }, [keyword])

  function openImage(target: ImageView) {
    navigate(`/image/${target.id}`, { state: { previewImage: target, from: 'search' } })
    void api.trackImageClick(target.id, 'search').catch(() => undefined)
  }

  function pickRelated(item: SearchSuggestionItem) {
    navigate(`/home?q=${encodeURIComponent(item.keyword)}`)
  }

  return (
    <div className="search-page">
      <main className="search-page__body">
        <section className="search-page__summary">
          <span>搜索</span>
          <strong>{keyword}</strong>
        </section>
        {loading && <section className="search-page__state">正在搜索...</section>}
        {!loading && error && <section className="search-page__state">{error}</section>}
        {!loading && related.length > 0 && (
          <section className="search-page__section search-page__section--plain">
            <div className="search-page__chips">
              {related.map((item) => (
                <button key={`${item.kind}-${item.keyword}`} type="button" onClick={() => pickRelated(item)}>
                  {item.keyword}
                </button>
              ))}
            </div>
          </section>
        )}
        {!loading && result.topics.length > 0 && (
          <section className="search-page__section">
            <h2>标签</h2>
            <div className="search-page__topic-row">
              {result.topics.map((topic) => (
                <button key={topic.id} type="button" onClick={() => navigate(`/home?q=${encodeURIComponent(topic.name)}`)}>
                  <strong>#{topic.name}</strong>
                  <span>{countText(topic.postCount)} 张图片</span>
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
                <article key={user.id} onClick={() => navigate(`/profile/${user.id}`)}>
                  <img src={avatarUrl(user.avatarUrl)} alt="" />
                  <span><strong>{user.nickname}</strong><small>@{user.username}</small></span>
                  <button type="button">主页</button>
                </article>
              ))}
            </div>
          </section>
        )}
        {!loading && result.images.length > 0 && (
          <section className="search-page__section search-page__section--plain">
            <h2>图片</h2>
            <MasonryGrid posts={result.images} onOpen={openImage} />
          </section>
        )}
        {!loading && !error && keyword.trim() && !result.images.length && !result.users.length && !result.topics.length && (
          <section className="search-page__state">没有找到相关内容</section>
        )}
      </main>
    </div>
  )
}
