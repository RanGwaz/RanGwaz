/** Compact keyword and topic discovery for the global search. */
import { Clock3, Flame, Loader2, Sparkles, X } from 'lucide-react'
import type { ReactNode } from 'react'
import type { SearchSuggestionItem } from '../types'
import { countText } from '../utils/format'

interface SearchFocusPanelProps {
  loading?: boolean
  query: string
  recent: SearchSuggestionItem[]
  recommended: SearchSuggestionItem[]
  trending: SearchSuggestionItem[]
  onClearRecent: () => void
  onPick: (item: SearchSuggestionItem) => void
}

interface SuggestionSectionProps {
  action?: ReactNode
  empty?: string
  icon: ReactNode
  items: SearchSuggestionItem[]
  onPick: (item: SearchSuggestionItem) => void
  title: string
}

function kindText(item: SearchSuggestionItem) {
  const count = item.postCount ? `${countText(item.postCount)} 张` : ''
  if (item.kind === 'category') return count || '分类'
  if (item.kind === 'tag') return count || '标签'
  if (item.kind === 'topic') return count || '主题'
  if (item.kind === 'recent') return '最近'
  return count || '关键词'
}

function SuggestionSection({ action, empty, icon, items, onPick, title }: SuggestionSectionProps) {
  if (!items.length && !empty) return null
  return (
    <section className="search-focus__section">
      <header>
        <span>{icon}<h2>{title}</h2></span>
        {action}
      </header>
      {items.length ? (
        <div className="search-focus__keywords">
          {items.slice(0, 10).map((item) => (
            <button key={`${item.kind}-${item.keyword}`} type="button" onClick={() => onPick(item)}>
              <strong>{item.kind === 'topic' ? `#${item.keyword}` : item.keyword}</strong>
              <small>{kindText(item)}</small>
            </button>
          ))}
        </div>
      ) : <p>{empty}</p>}
    </section>
  )
}

export function SearchFocusPanel({
  loading = false,
  query,
  recent,
  recommended,
  trending,
  onClearRecent,
  onPick,
}: SearchFocusPanelProps) {
  const hasQuery = Boolean(query.trim())

  return (
    <div id="global-search-suggestions" className="search-focus" role="dialog" aria-label="搜索建议">
      <div className="search-focus__inner">
        {!hasQuery && (
          <SuggestionSection
            action={recent.length ? <button className="search-focus__clear" type="button" onClick={onClearRecent}><X size={14} />清空</button> : null}
            icon={<Clock3 size={17} />}
            items={recent}
            onPick={onPick}
            title="最近搜索"
          />
        )}
        {!hasQuery && (
          <SuggestionSection
            icon={<Flame size={17} />}
            items={trending}
            onPick={onPick}
            title="热门主题"
          />
        )}
        <SuggestionSection
          empty={loading ? undefined : hasQuery ? '没有相关搜索建议' : '暂无灵感关键词'}
          icon={<Sparkles size={17} />}
          items={recommended}
          onPick={onPick}
          title={hasQuery ? '相关搜索' : '灵感关键词'}
        />
        {loading && (
          <p className="search-focus__loading" role="status">
            <Loader2 size={16} aria-hidden="true" />
            正在加载
          </p>
        )}
      </div>
    </div>
  )
}
