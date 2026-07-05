/** Phone authentication modal. */
import { Eye, EyeOff, KeyRound, Loader2, MessageSquare, Phone, ShieldCheck, X } from 'lucide-react'
import { FormEvent, useEffect, useMemo, useState } from 'react'
import { useAuth } from '../AuthContext'
import { BrandLogo } from './BrandLogo'

const AUTH_SMS_COOLDOWN_KEY = 'vibelo-auth-sms-cooldown'

type AuthMode = 'password' | 'code' | 'register'

function normalizePhoneInput(value: string) {
  const digits = value.replace(/\D/g, '')
  if (digits.startsWith('86') && digits.length > 11) return digits.slice(2, 13)
  return digits.slice(0, 11)
}

function isValidPhone(value: string) {
  return /^1[3-9]\d{9}$/.test(value)
}

function isUsablePassword(value: string) {
  const password = value.trim()
  return password.length >= 6 && password.length <= 64
}

function readCooldown(phone: string) {
  if (!phone) return 0
  try {
    const raw = localStorage.getItem(AUTH_SMS_COOLDOWN_KEY)
    if (!raw) return 0
    const value = JSON.parse(raw) as Record<string, number>
    const expiresAt = Number(value[phone] || 0)
    return Math.max(0, Math.ceil((expiresAt - Date.now()) / 1000))
  } catch {
    localStorage.removeItem(AUTH_SMS_COOLDOWN_KEY)
    return 0
  }
}

function rememberCooldown(phone: string, seconds: number) {
  try {
    const raw = localStorage.getItem(AUTH_SMS_COOLDOWN_KEY)
    const current = raw ? JSON.parse(raw) as Record<string, number> : {}
    current[phone] = Date.now() + Math.max(1, seconds) * 1000
    localStorage.setItem(AUTH_SMS_COOLDOWN_KEY, JSON.stringify(current))
  } catch {
    localStorage.setItem(AUTH_SMS_COOLDOWN_KEY, JSON.stringify({ [phone]: Date.now() + Math.max(1, seconds) * 1000 }))
  }
}

export function AuthModal() {
  const auth = useAuth()
  const [mode, setMode] = useState<AuthMode>('password')
  const [phone, setPhone] = useState('')
  const [password, setPassword] = useState('')
  const [smsCode, setSmsCode] = useState('')
  const [codePassword, setCodePassword] = useState('')
  const [codePasswordConfirm, setCodePasswordConfirm] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [showCodePassword, setShowCodePassword] = useState(false)
  const [mockCode, setMockCode] = useState('')
  const [cooldown, setCooldown] = useState(0)
  const [smsStatus, setSmsStatus] = useState<{ phone: string; registered: boolean } | null>(null)
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [sendingCode, setSendingCode] = useState(false)

  const cleanPhone = normalizePhoneInput(phone)
  const currentSmsStatus = smsStatus?.phone === cleanPhone ? smsStatus : null
  const registerPassword = codePassword.trim()
  const registerPasswordConfirm = codePasswordConfirm.trim()
  const isRegisterMode = mode === 'register'
  const canSubmit = useMemo(() => {
    if (submitting || !isValidPhone(cleanPhone)) return false
    if (mode === 'password') return password.trim().length > 0
    if (!/^\d{4,8}$/.test(smsCode.trim())) return false
    if (mode === 'register') {
      return isUsablePassword(codePassword) && codePassword.trim() === codePasswordConfirm.trim() && currentSmsStatus?.registered !== true
    }
    return true
  }, [cleanPhone, codePassword, codePasswordConfirm, currentSmsStatus?.registered, mode, password, smsCode, submitting])

  useEffect(() => {
    setCooldown(readCooldown(cleanPhone))
  }, [cleanPhone])

  useEffect(() => {
    if (!cooldown) return
    const timer = window.setInterval(() => setCooldown((value) => Math.max(0, value - 1)), 1000)
    return () => window.clearInterval(timer)
  }, [cooldown])

  if (!auth.authOpen) return null

  const title = mode === 'password' ? '密码登录' : mode === 'register' ? '注册账号' : '验证码登录'
  const subtitle = mode === 'password'
    ? '用手机号和密码登录，少发一次短信。'
    : mode === 'register'
      ? '先设置密码，再获取验证码完成注册。'
      : '已注册手机号可直接用验证码登录。'

  function switchMode(nextMode: AuthMode) {
    setMode(nextMode)
    setError('')
    setMockCode('')
  }

  function validateRegisterPassword() {
    if (!isUsablePassword(registerPassword)) throw new Error('请设置 6-64 位密码')
    if (registerPassword !== registerPasswordConfirm) throw new Error('两次输入的密码不一致')
  }

  async function sendCode() {
    setError('')
    setMockCode('')
    if (!isValidPhone(cleanPhone)) {
      setError('请输入有效的中国大陆手机号')
      return
    }
    if (isRegisterMode) {
      try {
        validateRegisterPassword()
      } catch (reason) {
        setError(reason instanceof Error ? reason.message : '请先设置密码')
        return
      }
    }
    const left = readCooldown(cleanPhone)
    if (left > 0) {
      setCooldown(left)
      setError(`验证码已发送，请 ${left} 秒后再试`)
      return
    }
    setSendingCode(true)
    try {
      const response = await auth.sendSmsCode(cleanPhone)
      const seconds = Math.max(1, response.cooldownSeconds || 60)
      rememberCooldown(cleanPhone, seconds)
      setCooldown(seconds)
      setSmsStatus({ phone: cleanPhone, registered: response.registered })
      setMockCode(response.mockCode || '')
      if (response.mockCode) setSmsCode(response.mockCode)
      if (response.registered && isRegisterMode) {
        setError('该手机号已注册，请直接登录或使用验证码登录')
      }
      if (!response.registered && mode === 'code') {
        setMode('register')
        setError('该手机号未注册，请设置密码后完成注册')
      }
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
      if (!isValidPhone(cleanPhone)) throw new Error('请输入有效的中国大陆手机号')
      if (mode === 'password') {
        if (!password.trim()) throw new Error('请输入密码')
        await auth.loginWithPhonePassword(cleanPhone, password.trim())
      } else if (mode === 'register') {
        if (currentSmsStatus?.registered === true) throw new Error('该手机号已注册，请直接登录')
        validateRegisterPassword()
        if (!/^\d{4,8}$/.test(smsCode.trim())) throw new Error('请输入正确验证码')
        await auth.loginWithPhone(cleanPhone, smsCode.trim(), registerPassword, registerPasswordConfirm)
      } else {
        if (currentSmsStatus?.registered === false) {
          setMode('register')
          throw new Error('该手机号未注册，请设置密码后完成注册')
        }
        if (!/^\d{4,8}$/.test(smsCode.trim())) throw new Error('请输入正确验证码')
        await auth.loginWithPhone(cleanPhone, smsCode.trim())
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
        <button className="auth-modal__close" type="button" onClick={auth.closeAuth} aria-label="关闭">
          <X size={18} />
        </button>

        <header className="auth-modal__header">
          <BrandLogo className="auth-modal__logo" />
          <span className="auth-modal__badge">
            <ShieldCheck size={14} />
            手机号认证
          </span>
          <div className="auth-modal__title">
            <h2>{title}</h2>
            <p>{subtitle}</p>
          </div>
        </header>

        <div className="auth-modal__tabs" role="tablist" aria-label="登录注册方式">
          <button type="button" className={mode === 'password' ? 'is-active' : undefined} onClick={() => switchMode('password')}>
            密码登录
          </button>
          <button type="button" className={mode === 'code' ? 'is-active' : undefined} onClick={() => switchMode('code')}>
            验证码登录
          </button>
          <button type="button" className={mode === 'register' ? 'is-active' : undefined} onClick={() => switchMode('register')}>
            注册账号
          </button>
        </div>

        <div className="auth-modal__fields">
          <label className="auth-modal__field">
            <span>手机号</span>
            <div className="auth-modal__phone-control">
              <input className="auth-modal__country-code" value="+86" readOnly aria-label="国家区号" tabIndex={-1} />
              <i aria-hidden="true" />
              <Phone size={18} />
              <input
                value={phone}
                onChange={(event) => setPhone(normalizePhoneInput(event.target.value))}
                placeholder="请输入手机号"
                autoComplete="tel"
                inputMode="numeric"
                maxLength={11}
              />
            </div>
          </label>

          {mode === 'password' && (
            <label className="auth-modal__field">
              <span>密码</span>
              <div className="auth-modal__password-control">
                <KeyRound size={18} />
                <input
                  value={password}
                  onChange={(event) => setPassword(event.target.value.slice(0, 64))}
                  placeholder="请输入密码"
                  type={showPassword ? 'text' : 'password'}
                  autoComplete="current-password"
                  maxLength={64}
                />
                <button
                  className="auth-modal__visibility"
                  type="button"
                  onClick={() => setShowPassword((value) => !value)}
                  aria-label={showPassword ? '隐藏密码' : '显示密码'}
                >
                  {showPassword ? <EyeOff size={17} /> : <Eye size={17} />}
                </button>
              </div>
            </label>
          )}

          {isRegisterMode && (
            <>
              <label className="auth-modal__field">
                <span>设置密码</span>
                <div className="auth-modal__password-control">
                  <KeyRound size={18} />
                  <input
                    value={codePassword}
                    onChange={(event) => setCodePassword(event.target.value.slice(0, 64))}
                    placeholder="请输入 6 位以上密码"
                    type={showCodePassword ? 'text' : 'password'}
                    autoComplete="new-password"
                    maxLength={64}
                  />
                  <button
                    className="auth-modal__visibility"
                    type="button"
                    onClick={() => setShowCodePassword((value) => !value)}
                    aria-label={showCodePassword ? '隐藏密码' : '显示密码'}
                  >
                    {showCodePassword ? <EyeOff size={17} /> : <Eye size={17} />}
                  </button>
                </div>
              </label>

              <label className="auth-modal__field">
                <span>确认密码</span>
                <div className="auth-modal__password-control">
                  <KeyRound size={18} />
                  <input
                    value={codePasswordConfirm}
                    onChange={(event) => setCodePasswordConfirm(event.target.value.slice(0, 64))}
                    placeholder="请再次输入密码"
                    type={showCodePassword ? 'text' : 'password'}
                    autoComplete="new-password"
                    maxLength={64}
                  />
                  <button
                    className="auth-modal__visibility"
                    type="button"
                    onClick={() => setShowCodePassword((value) => !value)}
                    aria-label={showCodePassword ? '隐藏密码' : '显示密码'}
                  >
                    {showCodePassword ? <EyeOff size={17} /> : <Eye size={17} />}
                  </button>
                </div>
              </label>
            </>
          )}

          {mode !== 'password' && (
            <label className="auth-modal__field">
              <span>验证码</span>
              <div className="auth-modal__code-control">
                <MessageSquare size={18} />
                <input
                  value={smsCode}
                  onChange={(event) => setSmsCode(event.target.value.replace(/\D/g, '').slice(0, 8))}
                  placeholder="6 位验证码"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                />
                <button type="button" onClick={() => void sendCode()} disabled={sendingCode || cooldown > 0}>
                  {sendingCode ? <Loader2 size={16} /> : cooldown > 0 ? `${cooldown}s` : '获取验证码'}
                </button>
              </div>
            </label>
          )}
        </div>

        {mode === 'password' && (
          <button className="auth-modal__secondary" type="button" onClick={() => switchMode('code')}>
            没有密码或忘记密码？用验证码登录
          </button>
        )}
        {mode === 'register' && (
          <button className="auth-modal__secondary" type="button" onClick={() => switchMode('password')}>
            已有账号？用密码登录
          </button>
        )}
        {mockCode && <p className="auth-modal__hint">本地验证码：{mockCode}</p>}
        {error && <p className="auth-modal__error">{error}</p>}

        <button className="auth-modal__submit" type="submit" disabled={!canSubmit}>
          {submitting && <Loader2 size={17} />}
          {mode === 'register' ? '注册并登录' : '登录'}
        </button>
      </form>
    </div>
  )
}
