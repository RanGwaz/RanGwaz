/** Main route composition for the React image website. */
import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { AuthProvider } from './AuthContext'
import { AppShell } from './components/AppShell'
import { AuthModal } from './components/AuthModal'
import { LaunchSplash } from './components/LaunchSplash'
import { DetailPage } from './pages/DetailPage'
import { DiscoverPage } from './pages/DiscoverPage'
import { FeedPage } from './pages/FeedPage'
import { ProfileEditPage } from './pages/ProfileEditPage'
import { ProfilePage } from './pages/ProfilePage'
import { ThemeProvider } from './ThemeContext'

export function App() {
  const location = useLocation()

  return (
    <ThemeProvider>
      <AuthProvider>
        <LaunchSplash />
        <AppShell>
          <Routes location={location}>
            <Route path="/" element={<Navigate to="/home" replace />} />
            <Route path="/home" element={<FeedPage />} />
            <Route path="/image/:id" element={<DetailPage />} />
            <Route path="/discover" element={<DiscoverPage />} />
            <Route path="/publish" element={<Navigate to="/home" replace />} />
            <Route path="/profile" element={<ProfilePage />} />
            <Route path="/profile/edit" element={<ProfileEditPage />} />
            <Route path="/profile/:id" element={<ProfilePage />} />
            <Route path="*" element={<Navigate to="/home" replace />} />
          </Routes>
        </AppShell>
        <AuthModal />
      </AuthProvider>
    </ThemeProvider>
  )
}
