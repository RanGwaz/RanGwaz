/** Main route composition for the React image website. */
import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { AuthProvider } from './AuthContext'
import { AppShell } from './components/AppShell'
import { AuthModal } from './components/AuthModal'
import { DetailPage } from './pages/DetailPage'
import { FeedPage } from './pages/FeedPage'
import { ProfilePage } from './pages/ProfilePage'
import { PublishPage } from './pages/PublishPage'
import { SearchPage } from './pages/SearchPage'

export function App() {
  const location = useLocation()

  return (
    <AuthProvider>
      <AppShell>
        <Routes location={location}>
          <Route path="/" element={<Navigate to="/home" replace />} />
          <Route path="/home" element={<FeedPage />} />
          <Route path="/image/:id" element={<DetailPage />} />
          <Route path="/discover" element={<SearchPage />} />
          <Route path="/publish" element={<PublishPage />} />
          <Route path="/profile" element={<ProfilePage />} />
          <Route path="/profile/:id" element={<ProfilePage />} />
          <Route path="*" element={<Navigate to="/home" replace />} />
        </Routes>
      </AppShell>
      <AuthModal />
    </AuthProvider>
  )
}
