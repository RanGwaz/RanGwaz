/** Compact keyword suggestions for the global topbar search. */
import { Clock3, Sparkles, X } from 'lucide-react'
import type { ReactNode } from 'react'
import type { SearchSuggestionItem } from '../types'

interface SearchFocusPanelProps {
  loading?: boolean
  query: string
  recent: SearchSuggestionItem[]
  recommended: SearchSuggestionItem[]
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

function kindText(kind?: string) {
  if (kind === 'category') return '分类'
  if (kind === 'tag') return '标签'
  if (kind === 'topic') return '话题'
  if (kind === 'recent') return '最近'
  return '关键词'
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
          {items.slice(0, 12).map((item) => (
            <button key={`${item.kind}-${item.keyword}`} type="button" onClick={() => onPick(item)}>
              <strong>{item.keyword}</strong>
              <small>{kindText(item.kind)}</small>
            </button>
          ))}
        </div>
      ) : <p>{empty}</p>}
    </section>
  )
}

export function SearchFocusPanel({ loading = false, query, recent, recommended, onClearRecent, onPick }: SearchFocusPanelProps) {
  return (
    <div className="search-focus" role="dialog" aria-label="搜索关键词建议">
      <div className="search-focus__inner">
        <SuggestionSection
          action={recent.length ? <button className="search-focus__clear" type="button" onClick={onClearRecent}><X size={14} />清空</button> : null}
          icon={<Clock3 size={17} />}
          items={recent}
          onPick={onPick}
          title="最近搜索"
        />
        <SuggestionSection
          empty={loading ? '正在整理关键词...' : query.trim() ? '暂无相关关键词' : '暂无推荐关键词'}
          icon={<Sparkles size={17} />}
          items={recommended}
          onPick={onPick}
          title="为你推荐"
        />
      </div>
    </div>
  )
}
