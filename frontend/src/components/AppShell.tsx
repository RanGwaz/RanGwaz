/** Top navigation shell for the Pinterest-style image feed. */
import { ChevronDown, Search } from 'lucide-react'
import { FormEvent, PropsWithChildren, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../AuthContext'
import { avatarUrl } from '../utils/format'
import { LeftRail } from './LeftRail'

export function AppShell({ children }: PropsWithChildren) {
  const [keyword, setKeyword] = useState('')
  const navigate = useNavigate()
  const auth = useAuth()

  function submit(event: FormEvent) {
    event.preventDefault()
    const q = keyword.trim()
    if (q) navigate(`/search?q=${encodeURIComponent(q)}`)
  }

  return (
    <div className="app-shell">
      <header className="app-shell__topbar">
        <form className="app-shell__search" onSubmit={submit}>
          <Search size={19} />
          <input value={keyword} onChange={(event) => setKeyword(event.target.value)} placeholder="搜索" />
        </form>
        <button className="app-shell__avatar-btn" type="button" onClick={auth.user ? () => navigate('/profile') : auth.openAuth}>
          {auth.user ? <img src={avatarUrl(auth.user.avatarUrl)} alt={auth.user.nickname} /> : <span>H</span>}
          <ChevronDown size={15} />
        </button>
      </header>
      <LeftRail />
      <main className="app-shell__main">{children}</main>
    </div>
  )
}
