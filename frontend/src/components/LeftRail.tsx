/** Compact left navigation rail for primary image-site actions. */
import { Home, Plus } from 'lucide-react'
import { NavLink, useNavigate } from 'react-router-dom'
import { BrandLogo } from './BrandLogo'

export function LeftRail() {
  const navigate = useNavigate()

  return (
    <aside className="left-rail" aria-label="页面导航">
      <button className="left-rail__logo" type="button" onClick={() => navigate('/home')} aria-label="回到首页" title="Vibelo">
        <BrandLogo compact />
      </button>
      <nav className="left-rail__nav">
        <NavLink to="/home" className={({ isActive }) => (isActive ? 'is-active' : '')} aria-label="首页" title="首页">
          <Home size={22} />
        </NavLink>
      </nav>
      <button className="left-rail__create" type="button" onClick={() => navigate('/publish')} aria-label="发布" title="发布">
        <Plus size={23} />
      </button>
    </aside>
  )
}
