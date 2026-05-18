/** Authentication context for local token-backed sessions. */
import { createContext, useContext, useEffect, useMemo, useState } from 'react'
import { api, getToken, setToken } from './services/api'
import type { UserSummary } from './types'

interface AuthContextValue {
  user: UserSummary | null
  token: string
  authOpen: boolean
  openAuth: () => void
  closeAuth: () => void
  login: (username: string, password: string) => Promise<void>
  register: (username: string, password: string, nickname: string) => Promise<void>
  logout: () => void
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<UserSummary | null>(null)
  const [token, setTokenState] = useState(getToken())
  const [authOpen, setAuthOpen] = useState(false)

  useEffect(() => {
    if (!token) return
    api.me().then((response) => setUser(response.me)).catch(() => {
      setToken('')
      setTokenState('')
      setUser(null)
    })
  }, [token])

  const value = useMemo<AuthContextValue>(() => ({
    user,
    token,
    authOpen,
    openAuth: () => setAuthOpen(true),
    closeAuth: () => setAuthOpen(false),
    login: async (username, password) => {
      const response = await api.login({ username, password })
      setToken(response.accessToken)
      setTokenState(response.accessToken)
      setUser(response.me)
      setAuthOpen(false)
    },
    register: async (username, password, nickname) => {
      const response = await api.register({ username, password, nickname })
      setToken(response.accessToken)
      setTokenState(response.accessToken)
      setUser(response.me)
      setAuthOpen(false)
    },
    logout: () => {
      setToken('')
      setTokenState('')
      setUser(null)
    },
  }), [authOpen, token, user])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth must be used inside AuthProvider')
  return context
}
