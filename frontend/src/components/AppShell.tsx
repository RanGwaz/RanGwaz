/** Top navigation shell for the image feed. */
import { ChevronDown, LogIn, LogOut, Moon, Plus, Search, Sun, User } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import type { CSSProperties, FormEvent, PropsWithChildren } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../AuthContext'
import { api } from '../services/api'
import { useTheme } from '../ThemeContext'
import type { SearchSuggestionItem, SearchSuggestionResponse } from '../types'
import { avatarUrl } from '../utils/format'
import { LeftRail } from './LeftRail'
import { SearchFocusPanel } from './SearchFocusPanel'

const RECENT_SEARCH_KEY = 'rangwaz-recent-searches'
const EMPTY_SUGGESTIONS: SearchSuggestionResponse = { recommended: [], trending: [] }
const DEFAULT_SEARCH_ANCHOR = { left: 88, top: 88, width: 720 }

function loadRecentSearches() {
  try {
    const parsed = JSON.parse(localStorage.getItem(RECENT_SEARCH_KEY) || '[]') as SearchSuggestionItem[]
    return Array.isArray(parsed) ? parsed.filter((item) => item?.keyword).slice(0, 10) : []
  } catch {
    localStorage.removeItem(RECENT_SEARCH_KEY)
    return []
  }
}

function saveRecentSearches(items: SearchSuggestionItem[]) {
  localStorage.setItem(RECENT_SEARCH_KEY, JSON.stringify(items.slice(0, 10)))
}

export function AppShell({ children }: PropsWithChildren) {
  const [keyword, setKeyword] = useState('')
  const [menuOpen, setMenuOpen] = useState(false)
  const [searchOpen, setSearchOpen] = useState(false)
  const [searchAnchor, setSearchAnchor] = useState(DEFAULT_SEARCH_ANCHOR)
  const [suggestions, setSuggestions] = useState<SearchSuggestionResponse>(EMPTY_SUGGESTIONS)
  const [suggestionsLoading, setSuggestionsLoading] = useState(false)
  const [recentSearches, setRecentSearches] = useState<SearchSuggestionItem[]>(() => loadRecentSearches())
  const menuRef = useRef<HTMLDivElement | null>(null)
  const searchRef = useRef<HTMLFormElement | null>(null)
  const searchPanelRef = useRef<HTMLDivElement | null>(null)
  const navigate = useNavigate()
  const location = useLocation()
  const auth = useAuth()
  const theme = useTheme()

  const updateSearchAnchor = useCallback(() => {
    const rect = searchRef.current?.getBoundingClientRect()
    if (!rect) return
    setSearchAnchor({
      left: Math.round(rect.left),
      top: Math.round(rect.bottom + 8),
      width: Math.round(rect.width),
    })
  }, [])

  function submit(event: FormEvent) {
    event.preventDefault()
    commitSearch({ keyword: keyword.trim(), kind: 'typed' })
  }

  useEffect(() => {
    const close = (event: MouseEvent) => {
      if (!menuRef.current?.contains(event.target as Node)) setMenuOpen(false)
      if (!searchRef.current?.contains(event.target as Node) && !searchPanelRef.current?.contains(event.target as Node)) {
        setSearchOpen(false)
      }
    }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [])

  useEffect(() => {
    if (location.pathname !== '/discover') return
    const params = new URLSearchParams(location.search)
    setKeyword(params.get('q') || '')
  }, [location.pathname, location.search])

  useEffect(() => {
    if (!searchOpen) return
    updateSearchAnchor()
    window.addEventListener('resize', updateSearchAnchor)
    window.addEventListener('scroll', updateSearchAnchor, true)
    return () => {
      window.removeEventListener('resize', updateSearchAnchor)
      window.removeEventListener('scroll', updateSearchAnchor, true)
    }
  }, [searchOpen, updateSearchAnchor])

  useEffect(() => {
    if (!searchOpen) return
    let cancelled = false
    const timer = window.setTimeout(() => {
      setSuggestionsLoading(true)
      api.searchSuggestions(keyword.trim())
        .then((next) => {
          if (!cancelled) setSuggestions(next)
        })
        .catch(() => {
          if (!cancelled) setSuggestions(EMPTY_SUGGESTIONS)
        })
        .finally(() => {
          if (!cancelled) setSuggestionsLoading(false)
        })
    }, 180)
    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
  }, [keyword, searchOpen])

  function openAuthed(path: string) {
    setMenuOpen(false)
    if (!auth.user) {
      auth.openAuth()
      return
    }
    navigate(path)
  }

  function commitSearch(item: SearchSuggestionItem) {
    const q = item.keyword.trim()
    if (!q) return
    const nextItem = { ...item, keyword: q, kind: item.kind || 'recent' }
    const nextRecent = [nextItem, ...recentSearches.filter((record) => record.keyword.toLowerCase() !== q.toLowerCase())].slice(0, 10)
    setRecentSearches(nextRecent)
    saveRecentSearches(nextRecent)
    setKeyword(q)
    setSearchOpen(false)
    navigate(`/discover?q=${encodeURIComponent(q)}`)
  }

  function clearRecentSearches() {
    setRecentSearches([])
    saveRecentSearches([])
  }

  return (
    <div className="app-shell">
      <header className="app-shell__topbar">
        <form className={searchOpen ? 'app-shell__search is-focused' : 'app-shell__search'} ref={searchRef} onSubmit={submit}>
          <Search size={19} />
          <input
            value={keyword}
            onChange={(event) => { setKeyword(event.target.value); updateSearchAnchor(); setSearchOpen(true) }}
            onFocus={() => { updateSearchAnchor(); setSearchOpen(true) }}
            onKeyDown={(event) => {
              if (event.key === 'Escape') setSearchOpen(false)
            }}
            placeholder="搜索图片、标签或用户"
          />
        </form>
        <div className="app-shell__actions">
          <button
            className="app-shell__icon-btn"
            type="button"
            onClick={theme.toggleTheme}
            aria-label={theme.resolvedTheme === 'dark' ? '切换浅色主题' : '切换深色主题'}
            title={theme.resolvedTheme === 'dark' ? '浅色主题' : '深色主题'}
          >
            {theme.resolvedTheme === 'dark' ? <Sun size={18} /> : <Moon size={18} />}
          </button>
          <div className="app-shell__account" ref={menuRef}>
            {auth.user ? (
              <>
                <button className="app-shell__avatar-btn" type="button" onClick={() => setMenuOpen((value) => !value)} aria-label="账户菜单">
                  <img src={avatarUrl(auth.user.avatarUrl)} alt={auth.user.nickname} />
                  <ChevronDown size={15} />
                </button>
                {menuOpen && (
                  <nav className="app-shell__account-menu" aria-label="账户菜单">
                    <button type="button" onClick={() => openAuthed('/profile')}><User size={17} />个人主页</button>
                    <button type="button" onClick={() => openAuthed('/publish')}><Plus size={17} />发布图片</button>
                    <button type="button" onClick={() => { setMenuOpen(false); void auth.logout() }}><LogOut size={17} />退出登录</button>
                  </nav>
                )}
              </>
            ) : (
              <button className="app-shell__login-btn" type="button" onClick={auth.openAuth}>
                <LogIn size={17} />
                登录
              </button>
            )}
          </div>
        </div>
      </header>
      {searchOpen && (
        <div
          ref={searchPanelRef}
          style={{
            '--search-panel-left': `${searchAnchor.left}px`,
            '--search-panel-top': `${searchAnchor.top}px`,
            '--search-panel-width': `${searchAnchor.width}px`,
          } as CSSProperties}
        >
          <SearchFocusPanel
            loading={suggestionsLoading}
            query={keyword}
            recent={recentSearches}
            recommended={suggestions.recommended}
            onClearRecent={clearRecentSearches}
            onPick={commitSearch}
          />
        </div>
      )}
      <LeftRail />
      <main className="app-shell__main">{children}</main>
    </div>
  )
}
