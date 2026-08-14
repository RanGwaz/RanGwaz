/** Search results for images, users, and topics. */
import { Loader2, RotateCcw, SearchX } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { MasonryGrid } from '../components/MasonryGrid'
import { api } from '../services/api'
import type { ImageView, SearchResult, SearchSuggestionItem } from '../types'
import { avatarUrl, countText } from '../utils/format'

const EMPTY_RESULT: SearchResult = { users: [], images: [], topics: [], related: [] }

export function SearchPage() {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const keyword = (params.get('q') || '').trim()
  const [result, setResult] = useState<SearchResult>(EMPTY_RESULT)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [retryKey, setRetryKey] = useState(0)
  const related = result.related ?? []
  const resultCount = useMemo(
    () => result.images.length + result.users.length + result.topics.length,
    [result.images.length, result.topics.length, result.users.length],
  )

  useEffect(() => {
    if (!keyword) {
      setResult(EMPTY_RESULT)
      setLoading(false)
      setError('')
      return
    }

    let cancelled = false
    setLoading(true)
    setError('')
    api.search(keyword)
      .then((nextResult) => {
        if (!cancelled) setResult(nextResult)
      })
      .catch((reason) => {
        if (!cancelled) {
          setResult(EMPTY_RESULT)
          setError(reason instanceof Error ? reason.message : '搜索失败')
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [keyword, retryKey])

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
        <header className="search-page__summary">
          <div>
            <span>搜索结果</span>
            <strong>“{keyword}”</strong>
          </div>
          {!loading && !error && <small>{resultCount} 项</small>}
        </header>

        {loading && (
          <section className="search-page__state search-page__state--loading" role="status">
            <Loader2 size={20} aria-hidden="true" />
            正在搜索
          </section>
        )}

        {!loading && error && (
          <section className="search-page__state search-page__state--error" role="alert">
            <span>{error}</span>
            <button type="button" onClick={() => setRetryKey((value) => value + 1)}>
              <RotateCcw size={15} aria-hidden="true" />
              重试
            </button>
          </section>
        )}

        {!loading && !error && related.length > 0 && (
          <section className="search-page__section search-page__section--plain" aria-label="相关搜索">
            <div className="search-page__chips">
              {related.map((item) => (
                <button key={`${item.kind}-${item.keyword}`} type="button" onClick={() => pickRelated(item)}>
                  {item.keyword}
                </button>
              ))}
            </div>
          </section>
        )}

        {!loading && !error && result.topics.length > 0 && (
          <section className="search-page__section">
            <h2>相关主题</h2>
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

        {!loading && !error && result.users.length > 0 && (
          <section className="search-page__section">
            <h2>相关用户</h2>
            <div className="search-page__user-list">
              {result.users.map((user) => (
                <button className="search-page__user-card" key={user.id} type="button" onClick={() => navigate(`/profile/${user.id}`)}>
                  <img src={avatarUrl(user.avatarUrl)} alt={user.nickname} />
                  <span><strong>{user.nickname}</strong><small>@{user.username}</small></span>
                  <em>查看主页</em>
                </button>
              ))}
            </div>
          </section>
        )}

        {!loading && !error && result.images.length > 0 && (
          <section className="search-page__section search-page__section--plain">
            <h2>相关图片</h2>
            <MasonryGrid posts={result.images} onOpen={openImage} />
          </section>
        )}

        {!loading && !error && keyword && resultCount === 0 && (
          <section className="search-page__state search-page__state--empty">
            <SearchX size={22} aria-hidden="true" />
            <strong>没有找到相关内容</strong>
            <span>换个关键词试试</span>
          </section>
        )}
      </main>
    </div>
  )
}
