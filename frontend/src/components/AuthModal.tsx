/** Login, phone verification, and registration modal. */
import { Loader2, Lock, MessageSquare, Phone, UserRound, X } from 'lucide-react'
import { FormEvent, useEffect, useState } from 'react'
import { useAuth } from '../AuthContext'
import { BrandLogo } from './BrandLogo'

type AuthMode = 'phone' | 'password' | 'register'

export function AuthModal() {
  const auth = useAuth()
  const [mode, setMode] = useState<AuthMode>('phone')
  const [phone, setPhone] = useState('')
  const [smsCode, setSmsCode] = useState('')
  const [mockCode, setMockCode] = useState('')
  const [cooldown, setCooldown] = useState(0)
  const [username, setUsername] = useState('mira')
  const [password, setPassword] = useState('RanGwaz147..')
  const [nickname, setNickname] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [sendingCode, setSendingCode] = useState(false)

  useEffect(() => {
    if (!cooldown) return
    const timer = window.setInterval(() => setCooldown((value) => Math.max(0, value - 1)), 1000)
    return () => window.clearInterval(timer)
  }, [cooldown])

  if (!auth.authOpen) return null

  function switchMode(nextMode: AuthMode) {
    setMode(nextMode)
    setError('')
  }

  async function sendCode() {
    setError('')
    const cleanPhone = phone.trim()
    if (cleanPhone.length < 8) {
      setError('请输入有效手机号')
      return
    }
    setSendingCode(true)
    try {
      const code = await auth.sendSmsCode(cleanPhone)
      setMockCode(code)
      if (code) setSmsCode(code)
      setCooldown(60)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '验证码发送失败')
    } finally {
      setSendingCode(false)
    }
  }

  async function submit(event: FormEvent) {
    event.preventDefault()
    setError('')
    setSubmitting(true)
    try {
      if (mode === 'phone') {
        if (!phone.trim() || !smsCode.trim()) throw new Error('请输入手机号和验证码')
        await auth.loginWithPhone(phone.trim(), smsCode.trim())
      } else if (mode === 'password') {
        if (username.trim().length < 2) throw new Error('用户名至少需要 2 个字符')
        if (password.length < 6) throw new Error('密码至少需要 6 位')
        await auth.login(username.trim(), password)
      } else {
        if (username.trim().length < 2) throw new Error('用户名至少需要 2 个字符')
        if (password.length < 6) throw new Error('密码至少需要 6 位')
        if ((nickname || username).trim().length < 2) throw new Error('昵称至少需要 2 个字符')
        await auth.register(username.trim(), password, (nickname || username).trim())
      }
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
          <BrandLogo />
          <h2>欢迎回来</h2>
          <p>继续浏览、收藏和发布你的图片灵感。</p>
          <div>
            <span>Vibelo</span>
            <span>Image Feed</span>
            <span>Visual Search</span>
          </div>
        </section>
        <section className="auth-modal__right">
          <BrandLogo className="auth-modal__mobile-logo" />
          <h2>{mode === 'register' ? '创建账号' : '登录 Vibelo'}</h2>
          <div className="auth-modal__tabs">
            <button type="button" className={mode === 'phone' ? 'is-active' : ''} onClick={() => switchMode('phone')}>手机号</button>
            <button type="button" className={mode === 'password' ? 'is-active' : ''} onClick={() => switchMode('password')}>密码</button>
            <button type="button" className={mode === 'register' ? 'is-active' : ''} onClick={() => switchMode('register')}>注册</button>
          </div>

          {mode === 'phone' ? (
            <>
              <label>
                手机号
                <span><Phone size={17} /><input value={phone} onChange={(event) => setPhone(event.target.value)} placeholder="请输入手机号" autoComplete="tel" inputMode="tel" /></span>
              </label>
              <label>
                验证码
                <div className="auth-modal__code-row">
                  <span><MessageSquare size={17} /><input value={smsCode} onChange={(event) => setSmsCode(event.target.value)} placeholder="6 位验证码" inputMode="numeric" /></span>
                  <button type="button" onClick={() => void sendCode()} disabled={sendingCode || cooldown > 0}>
                    {sendingCode ? <Loader2 size={16} /> : cooldown > 0 ? `${cooldown}s` : '获取'}
                  </button>
                </div>
              </label>
              {mockCode && <p className="auth-modal__hint">本地验证码：{mockCode}</p>}
            </>
          ) : (
            <>
              <label>
                用户名
                <span><UserRound size={17} /><input value={username} onChange={(event) => setUsername(event.target.value)} placeholder="请输入用户名" autoComplete="username" /></span>
              </label>
              <label>
                密码
                <span><Lock size={17} /><input value={password} onChange={(event) => setPassword(event.target.value)} type="password" placeholder="请输入密码" autoComplete={mode === 'password' ? 'current-password' : 'new-password'} /></span>
              </label>
              {mode === 'register' && (
                <label>
                  昵称
                  <span><UserRound size={17} /><input value={nickname} onChange={(event) => setNickname(event.target.value)} placeholder="主页显示名称" /></span>
                </label>
              )}
            </>
          )}

          {error && <p className="auth-modal__error">{error}</p>}
          <button className="auth-modal__submit" type="submit" disabled={submitting}>
            {submitting && <Loader2 size={17} />}
            {mode === 'register' ? '注册并登录' : '登录'}
          </button>
          {mode === 'password' && <p className="auth-modal__hint">开发账号：mira / RanGwaz147..</p>}
        </section>
      </form>
    </div>
  )
}
