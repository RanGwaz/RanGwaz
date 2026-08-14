/** Lightweight discovery page backed by trending topics. */
import { Compass, Loader2, RotateCcw } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../services/api'
import type { SearchSuggestionItem } from '../types'
import { countText } from '../utils/format'

function mergeDiscoverItems(...groups: SearchSuggestionItem[][]) {
  const seen = new Set<string>()
  return groups.flat().filter((item) => {
    const key = item.keyword.trim().toLocaleLowerCase()
    if (!key || seen.has(key)) return false
    seen.add(key)
    return true
  }).slice(0, 24)
}

export function DiscoverPage() {
  const navigate = useNavigate()
  const [items, setItems] = useState<SearchSuggestionItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [retryKey, setRetryKey] = useState(0)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError('')
    Promise.all([
      api.trendingTopics(24).catch(() => []),
      api.searchSuggestions(''),
    ])
      .then(([topics, suggestions]) => {
        if (cancelled) return
        const topicItems: SearchSuggestionItem[] = topics.map((topic) => ({
          keyword: topic.name,
          kind: 'topic',
          imageUrl: topic.coverUrl,
          postCount: topic.postCount,
        }))
        setItems(mergeDiscoverItems(topicItems, suggestions.trending, suggestions.recommended))
      })
      .catch((reason) => {
        if (!cancelled) {
          setItems([])
          setError(reason instanceof Error ? reason.message : '灵感加载失败')
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [retryKey])

  function openItem(item: SearchSuggestionItem) {
    navigate(`/home?q=${encodeURIComponent(item.keyword)}`)
  }

  return (
    <div className="discover-page">
      <main className="discover-page__main">
        <header className="discover-page__header">
          <Compass size={22} aria-hidden="true" />
          <h1>发现灵感</h1>
        </header>

        {loading && (
          <div className="discover-page__state" role="status">
            <Loader2 size={20} aria-hidden="true" />
            正在加载
          </div>
        )}

        {!loading && error && (
          <div className="discover-page__state" role="alert">
            <span>{error}</span>
            <button type="button" onClick={() => setRetryKey((value) => value + 1)}>
              <RotateCcw size={15} aria-hidden="true" />
              重试
            </button>
          </div>
        )}

        {!loading && !error && items.length > 0 && (
          <section className="discover-page__grid" aria-label="热门主题与灵感">
            {items.map((item) => (
              <button key={`${item.kind}-${item.keyword}`} type="button" onClick={() => openItem(item)}>
                {item.imageUrl ? <img src={item.imageUrl} alt="" loading="lazy" /> : <i aria-hidden="true">#</i>}
                <span>
                  <strong>{item.kind === 'topic' ? '#' : ''}{item.keyword}</strong>
                  <small>{item.postCount ? `${countText(item.postCount)} 张图片` : '查看相关图片'}</small>
                </span>
              </button>
            ))}
          </section>
        )}

        {!loading && !error && items.length === 0 && (
          <div className="discover-page__state">暂无可用灵感</div>
        )}
      </main>
    </div>
  )
}
