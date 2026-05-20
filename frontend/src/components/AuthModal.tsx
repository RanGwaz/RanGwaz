/** Login and registration modal matching the existing soft overlay style. */
import { Loader2, Lock, UserRound, X } from 'lucide-react'
import { FormEvent, useState } from 'react'
import { useAuth } from '../AuthContext'

export function AuthModal() {
  const auth = useAuth()
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [username, setUsername] = useState('mira')
  const [password, setPassword] = useState('123456')
  const [nickname, setNickname] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  if (!auth.authOpen) return null

  async function submit(event: FormEvent) {
    event.preventDefault()
    setError('')
    if (username.trim().length < 2) {
      setError('用户名至少需要 2 个字符')
      return
    }
    if (password.length < 6) {
      setError('密码至少需要 6 位')
      return
    }
    if (mode === 'register' && (nickname || username).trim().length < 2) {
      setError('昵称至少需要 2 个字符')
      return
    }
    setSubmitting(true)
    try {
      if (mode === 'login') await auth.login(username.trim(), password)
      else await auth.register(username.trim(), password, (nickname || username).trim())
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '登录失败')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="auth-overlay" onMouseDown={auth.closeAuth}>
      <form className="auth-modal" onSubmit={submit} onMouseDown={(event) => event.stopPropagation()}>
        <button className="auth-modal__close" type="button" onClick={auth.closeAuth} aria-label="关闭"><X size={20} /></button>
        <section className="auth-modal__left">
          <span>RanGwaz</span>
          <h2>收藏灵感，发布生活里的好画面</h2>
          <p>登录后可以发布图片、关注创作者、点赞收藏并维护自己的主页。</p>
        </section>
        <section className="auth-modal__right">
          <h2>{mode === 'login' ? '欢迎回来' : '创建账号'}</h2>
          <div className="auth-modal__tabs">
            <button type="button" className={mode === 'login' ? 'is-active' : ''} onClick={() => setMode('login')}>用户名密码</button>
            <button type="button" className={mode === 'register' ? 'is-active' : ''} onClick={() => setMode('register')}>注册账号</button>
          </div>
          <label>
            用户名
            <span><UserRound size={17} /><input value={username} onChange={(event) => setUsername(event.target.value)} placeholder="请输入用户名" autoComplete="username" /></span>
          </label>
          <label>
            密码
            <span><Lock size={17} /><input value={password} onChange={(event) => setPassword(event.target.value)} type="password" placeholder="请输入密码" autoComplete={mode === 'login' ? 'current-password' : 'new-password'} /></span>
          </label>
          {mode === 'register' && (
            <label>
              昵称
              <span><UserRound size={17} /><input value={nickname} onChange={(event) => setNickname(event.target.value)} placeholder="主页展示名称" /></span>
            </label>
          )}
          {error && <p className="auth-modal__error">{error}</p>}
          <button className="auth-modal__submit" type="submit" disabled={submitting}>
            {submitting && <Loader2 size={17} />}
            {mode === 'login' ? '登录' : '注册并登录'}
          </button>
          <p className="auth-modal__hint">测试账号：mira / 123456</p>
        </section>
      </form>
    </div>
  )
}
