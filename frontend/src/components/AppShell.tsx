/** Top navigation shell for the Pinterest-style image feed. */
import { ChevronDown, LogIn, LogOut, Plus, Search, User } from 'lucide-react'
import { FormEvent, PropsWithChildren, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../AuthContext'
import { avatarUrl } from '../utils/format'
import { LeftRail } from './LeftRail'

export function AppShell({ children }: PropsWithChildren) {
  const [keyword, setKeyword] = useState('')
  const [menuOpen, setMenuOpen] = useState(false)
  const menuRef = useRef<HTMLDivElement | null>(null)
  const navigate = useNavigate()
  const auth = useAuth()

  function submit(event: FormEvent) {
    event.preventDefault()
    const q = keyword.trim()
    if (q) navigate(`/search?q=${encodeURIComponent(q)}`)
  }

  useEffect(() => {
    const close = (event: MouseEvent) => {
      if (!menuRef.current?.contains(event.target as Node)) setMenuOpen(false)
    }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [])

  function openAuthed(path: string) {
    setMenuOpen(false)
    if (!auth.user) {
      auth.openAuth()
      return
    }
    navigate(path)
  }

  return (
    <div className="app-shell">
      <header className="app-shell__topbar">
        <form className="app-shell__search" onSubmit={submit}>
          <Search size={19} />
          <input value={keyword} onChange={(event) => setKeyword(event.target.value)} placeholder="搜索" />
        </form>
        <div className="app-shell__account" ref={menuRef}>
          <button className="app-shell__avatar-btn" type="button" onClick={() => (auth.user ? setMenuOpen((value) => !value) : auth.openAuth())}>
            {auth.user ? <img src={avatarUrl(auth.user.avatarUrl)} alt={auth.user.nickname} /> : <span>H</span>}
            <ChevronDown size={15} />
          </button>
          {menuOpen && (
            <nav className="app-shell__account-menu" aria-label="账户菜单">
              {auth.user ? (
                <>
                  <button type="button" onClick={() => openAuthed('/profile')}><User size={17} />个人资料</button>
                  <button type="button" onClick={() => openAuthed('/publish')}><Plus size={17} />发布图片</button>
                  <button type="button" onClick={() => { setMenuOpen(false); void auth.logout() }}><LogOut size={17} />退出登录</button>
                </>
              ) : <button type="button" onClick={auth.openAuth}><LogIn size={17} />登录 / 注册</button>}
            </nav>
          )}
        </div>
      </header>
      <LeftRail />
      <main className="app-shell__main">{children}</main>
    </div>
  )
}
