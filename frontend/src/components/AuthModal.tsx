/** Login and registration modal matching the existing soft overlay style. */
import { FormEvent, useState } from 'react'
import { useAuth } from '../AuthContext'

export function AuthModal() {
  const auth = useAuth()
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [username, setUsername] = useState('mira')
  const [password, setPassword] = useState('123456')
  const [nickname, setNickname] = useState('')
  const [error, setError] = useState('')

  if (!auth.authOpen) return null

  async function submit(event: FormEvent) {
    event.preventDefault()
    setError('')
    try {
      if (mode === 'login') await auth.login(username, password)
      else await auth.register(username, password, nickname || username)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '登录失败')
    }
  }

  return (
    <div className="auth-overlay">
      <form className="auth-modal" onSubmit={submit}>
        <button className="auth-modal__close" type="button" onClick={auth.closeAuth}>×</button>
        <section className="auth-modal__left">
          <span>登录后推荐更懂你的笔记</span>
          <div className="auth-modal__qr" />
          <p>使用右侧方式登录 / 注册</p>
          <small>新用户首次登录将自动创建账号</small>
        </section>
        <section className="auth-modal__right">
          <h2>欢迎回来</h2>
          <div className="auth-modal__tabs">
            <button type="button" className={mode === 'login' ? 'is-active' : ''} onClick={() => setMode('login')}>用户名密码</button>
            <button type="button" className={mode === 'register' ? 'is-active' : ''} onClick={() => setMode('register')}>注册账号</button>
          </div>
          <label>
            用户名
            <input value={username} onChange={(event) => setUsername(event.target.value)} placeholder="请输入用户名" />
          </label>
          <label>
            密码
            <input value={password} onChange={(event) => setPassword(event.target.value)} type="password" placeholder="请输入密码" />
          </label>
          {mode === 'register' && (
            <label>
              昵称
              <input value={nickname} onChange={(event) => setNickname(event.target.value)} placeholder="首次注册时使用" />
            </label>
          )}
          {error && <p className="auth-modal__error">{error}</p>}
          <button className="auth-modal__submit" type="submit">{mode === 'login' ? '登录' : '注册'}</button>
          <p className="auth-modal__hint">测试账号：mira / 123456</p>
        </section>
      </form>
    </div>
  )
}
