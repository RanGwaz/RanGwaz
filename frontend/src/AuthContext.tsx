/** Authentication context for local token-backed sessions. */
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { api, getToken, setToken } from './services/api'
import type { UserSummary } from './types'

interface AuthContextValue {
  user: UserSummary | null
  token: string
  authOpen: boolean
  ready: boolean
  openAuth: () => void
  closeAuth: () => void
  login: (username: string, password: string) => Promise<void>
  register: (username: string, password: string, nickname: string) => Promise<void>
  logout: () => Promise<void>
  updateUser: (user: UserSummary) => void
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<UserSummary | null>(null)
  const [token, setTokenState] = useState(getToken())
  const [authOpen, setAuthOpen] = useState(false)
  const [ready, setReady] = useState(!getToken())

  useEffect(() => {
    if (!token) {
      setReady(true)
      return
    }
    setReady(false)
    api.me().then((response) => setUser(response.me)).catch(() => {
      setToken('')
      setTokenState('')
      setUser(null)
    }).finally(() => setReady(true))
  }, [token])

  const openAuth = useCallback(() => setAuthOpen(true), [])
  const closeAuth = useCallback(() => setAuthOpen(false), [])

  const login = useCallback(async (username: string, password: string) => {
    const response = await api.login({ username, password })
    setToken(response.accessToken)
    setTokenState(response.accessToken)
    setUser(response.me)
    setAuthOpen(false)
  }, [])

  const register = useCallback(async (username: string, password: string, nickname: string) => {
    const response = await api.register({ username, password, nickname })
    setToken(response.accessToken)
    setTokenState(response.accessToken)
    setUser(response.me)
    setAuthOpen(false)
  }, [])

  const logout = useCallback(async () => {
    await api.logout().catch(() => undefined)
    setToken('')
    setTokenState('')
    setUser(null)
    setAuthOpen(false)
  }, [])

  const updateUser = useCallback((nextUser: UserSummary) => setUser(nextUser), [])

  const value = useMemo<AuthContextValue>(() => ({
    user,
    token,
    authOpen,
    ready,
    openAuth,
    closeAuth,
    login,
    register,
    logout,
    updateUser,
  }), [authOpen, closeAuth, login, logout, openAuth, ready, register, token, updateUser, user])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth must be used inside AuthProvider')
  return context
}
