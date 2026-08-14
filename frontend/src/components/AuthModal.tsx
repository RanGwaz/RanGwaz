/** Phone-first sign-in, registration, and password reset dialog. */
import { Eye, EyeOff, KeyRound, Loader2, MessageSquare, Phone, X } from 'lucide-react'
import { type FormEvent, useEffect, useMemo, useRef, useState } from 'react'
import { useAuth } from '../AuthContext'
import type { SmsCodeResponse } from '../types'
import { BrandLogo } from './BrandLogo'

const AUTH_SMS_COOLDOWN_KEY = 'vibelo-auth-sms-cooldown'
const PASSWORD_MIN_LENGTH = 8
const PASSWORD_MAX_LENGTH = 64

type AuthMode = 'password' | 'code'
type CodeAction = 'login' | 'reset'
type SmsScene = 'login' | 'password_reset'
type AccountState = 'unknown' | 'existing' | 'new'

interface StoredChallenge {
  cooldownUntil: number
  expiresAt: number
  registered: boolean
}

interface ChallengeState {
  account: AccountState
  cooldown: number
}

function normalizePhoneInput(value: string) {
  const digits = value.replace(/\D/g, '')
  if (digits.startsWith('86') && digits.length > 11) return digits.slice(2, 13)
  return digits.slice(0, 11)
}

function isValidPhone(value: string) {
  return /^1[3-9]\d{9}$/.test(value)
}

function loadStoredChallenges() {
  try {
    const parsed = JSON.parse(localStorage.getItem(AUTH_SMS_COOLDOWN_KEY) || '{}') as Record<string, StoredChallenge | number>
    return parsed && typeof parsed === 'object' ? parsed : {}
  } catch {
    return {}
  }
}

function smsScene(action: CodeAction): SmsScene {
  return action === 'reset' ? 'password_reset' : 'login'
}

function challengeStorageKey(phone: string, scene: SmsScene) {
  return `${scene}:${phone}`
}

function readChallenge(phone: string, scene: SmsScene): ChallengeState {
  if (!phone) return { account: 'unknown', cooldown: 0 }
  const challenges = loadStoredChallenges()
  const stored = challenges[challengeStorageKey(phone, scene)]
    ?? (scene === 'login' ? challenges[phone] : undefined)
  if (!stored) return { account: 'unknown', cooldown: 0 }

  // Older versions stored only the cooldown timestamp. Keep it readable without
  // trusting it as proof that this is an existing or a new account.
  if (typeof stored === 'number') {
    return {
      account: 'unknown',
      cooldown: Math.max(0, Math.ceil((stored - Date.now()) / 1000)),
    }
  }

  const challengeActive = Number(stored.expiresAt) > Date.now()
  const account = stored.registered === true ? 'existing' : stored.registered === false ? 'new' : 'unknown'
  return {
    account: challengeActive ? account : 'unknown',
    cooldown: Math.max(0, Math.ceil((Number(stored.cooldownUntil) - Date.now()) / 1000)),
  }
}

function rememberChallenge(phone: string, scene: SmsScene, response: SmsCodeResponse) {
  try {
    const current = loadStoredChallenges()
    const now = Date.now()
    current[challengeStorageKey(phone, scene)] = {
      cooldownUntil: now + Math.max(1, response.cooldownSeconds || 60) * 1000,
      expiresAt: now + Math.max(1, response.expiresInSeconds || 300) * 1000,
      registered: response.registered,
    }
    localStorage.setItem(AUTH_SMS_COOLDOWN_KEY, JSON.stringify(current))
  } catch {
    // Storage can be disabled by the browser. The active in-memory challenge
    // still works and the backend remains the source of truth for cooldowns.
  }
}

function markChallengeRegistered(phone: string) {
  try {
    const current = loadStoredChallenges()
    let changed = false
    for (const key of [phone, challengeStorageKey(phone, 'login'), challengeStorageKey(phone, 'password_reset')]) {
      const stored = current[key]
      if (!stored || typeof stored === 'number') continue
      current[key] = { ...stored, registered: true }
      changed = true
    }
    if (!changed) return
    localStorage.setItem(AUTH_SMS_COOLDOWN_KEY, JSON.stringify(current))
  } catch {
    // Authentication must not fail because browser storage is unavailable.
  }
}

function passwordBytes(value: string) {
  return new TextEncoder().encode(value).length
}

function passwordIsUsable(value: string) {
  const length = value.length
  return value.trim().length > 0
    && length >= PASSWORD_MIN_LENGTH
    && length <= PASSWORD_MAX_LENGTH
    && passwordBytes(value) <= 72
}

function passwordCanLogin(value: string) {
  return value.length > 0 && value.length <= PASSWORD_MAX_LENGTH && value.trim().length > 0
}

export function AuthModal() {
  const auth = useAuth()
  const [mode, setMode] = useState<AuthMode>('code')
  const [codeAction, setCodeAction] = useState<CodeAction>('login')
  const [account, setAccount] = useState<AccountState>('unknown')
  const [phone, setPhone] = useState('')
  const [password, setPassword] = useState('')
  const [passwordConfirm, setPasswordConfirm] = useState('')
  const [smsCode, setSmsCode] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [mockCode, setMockCode] = useState('')
  const [cooldown, setCooldown] = useState(0)
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [sendingCode, setSendingCode] = useState(false)

  const cleanPhone = normalizePhoneInput(phone)
  const activeSmsFlow = useRef({ open: auth.authOpen, phone: cleanPhone, scene: smsScene(codeAction) })
  activeSmsFlow.current = { open: auth.authOpen, phone: cleanPhone, scene: smsScene(codeAction) }
  const needsNewPassword = mode === 'code' && (account === 'new' || codeAction === 'reset')
  const resetAccountMissing = codeAction === 'reset' && account === 'new'
  const effectiveCodeAction = codeAction === 'reset' ? 'reset' : account === 'new' ? 'register' : 'login'
  const passwordTooLong = needsNewPassword && passwordBytes(password) > 72
  const passwordOnlyWhitespace = needsNewPassword && password.length > 0 && password.trim().length === 0
  const passwordsMismatch = needsNewPassword && passwordConfirm.length > 0 && password !== passwordConfirm
  const canSubmit = useMemo(() => {
    if (submitting || sendingCode || !isValidPhone(cleanPhone)) return false
    if (mode === 'password') return passwordCanLogin(password)
    if (account === 'unknown' || resetAccountMissing || !/^\d{4,8}$/.test(smsCode.trim())) return false
    if (!needsNewPassword) return true
    return passwordIsUsable(password) && password === passwordConfirm
  }, [account, cleanPhone, mode, needsNewPassword, password, passwordConfirm, resetAccountMissing, sendingCode, smsCode, submitting])

  useEffect(() => {
    if (cooldown <= 0) return
    const timer = window.setTimeout(() => setCooldown((value) => Math.max(0, value - 1)), 1000)
    return () => window.clearTimeout(timer)
  }, [cooldown])

  useEffect(() => {
    if (!auth.authOpen) return
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !submitting) auth.closeAuth()
    }
    document.addEventListener('keydown', closeOnEscape)
    return () => document.removeEventListener('keydown', closeOnEscape)
  }, [auth, submitting])

  useEffect(() => {
    if (auth.authOpen) {
      const challenge = readChallenge(cleanPhone, smsScene(codeAction))
      setAccount(challenge.account)
      setCooldown(challenge.cooldown)
      return
    }
    setPassword('')
    setPasswordConfirm('')
    setSmsCode('')
    setMockCode('')
    setError('')
    setShowPassword(false)
    setCodeAction('login')
  }, [auth.authOpen])

  if (!auth.authOpen) return null

  function handlePhoneChange(value: string) {
    const nextPhone = normalizePhoneInput(value)
    if (nextPhone === phone) return
    const challenge = readChallenge(nextPhone, smsScene(codeAction))
    setPhone(nextPhone)
    setAccount(challenge.account)
    setCooldown(challenge.cooldown)
    setSmsCode('')
    setPassword('')
    setPasswordConfirm('')
    setMockCode('')
    setError('')
  }

  function switchMode(nextMode: AuthMode) {
    const challenge = readChallenge(cleanPhone, 'login')
    setMode(nextMode)
    setCodeAction('login')
    setAccount(challenge.account)
    setCooldown(challenge.cooldown)
    setSmsCode('')
    setMockCode('')
    setPassword('')
    setPasswordConfirm('')
    setShowPassword(false)
    setError('')
  }

  function toggleReset() {
    const nextAction: CodeAction = codeAction === 'reset' ? 'login' : 'reset'
    const challenge = readChallenge(cleanPhone, smsScene(nextAction))
    setCodeAction(nextAction)
    setAccount(challenge.account)
    setCooldown(challenge.cooldown)
    setSmsCode('')
    setMockCode('')
    setPassword('')
    setPasswordConfirm('')
    setShowPassword(false)
    setError('')
  }

  function beginReset() {
    const challenge = readChallenge(cleanPhone, 'password_reset')
    setMode('code')
    setCodeAction('reset')
    setAccount(challenge.account)
    setCooldown(challenge.cooldown)
    setSmsCode('')
    setPassword('')
    setPasswordConfirm('')
    setShowPassword(false)
    setError('')
  }

  async function sendCode() {
    setError('')
    setMockCode('')
    if (!isValidPhone(cleanPhone)) {
      setError('请输入有效的中国大陆手机号')
      return
    }
    const requestPhone = cleanPhone
    const scene = smsScene(codeAction)
    const remembered = readChallenge(requestPhone, scene)
    if (remembered.cooldown > 0) {
      setCooldown(remembered.cooldown)
      setAccount(remembered.account)
      setError(codeAction === 'reset' && remembered.account === 'new'
        ? '该手机号尚未注册，请返回验证码登录完成注册'
        : `验证码已发送，请 ${remembered.cooldown} 秒后再试`)
      return
    }
    setSendingCode(true)
    try {
      const response = await auth.sendSmsCode(requestPhone, scene)
      rememberChallenge(requestPhone, scene, response)
      const active = activeSmsFlow.current
      if (!active.open || active.phone !== requestPhone || active.scene !== scene) return
      setCooldown(Math.max(1, response.cooldownSeconds || 60))
      setAccount(response.registered ? 'existing' : 'new')
      setMockCode(response.mockCode || '')
      if (response.mockCode) setSmsCode(response.mockCode)
      if (scene === 'password_reset' && !response.registered) {
        setError('该手机号尚未注册，请返回验证码登录完成注册')
      }
    } catch (reason) {
      const active = activeSmsFlow.current
      if (active.open && active.phone === requestPhone && active.scene === scene) {
        setError(reason instanceof Error ? reason.message : '验证码发送失败')
      }
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
        if (!passwordCanLogin(password)) throw new Error('请输入密码')
        await auth.loginWithPhonePassword(cleanPhone, password)
        markChallengeRegistered(cleanPhone)
        return
      }
      if (account === 'unknown') throw new Error('请先获取验证码')
      if (!/^\d{4,8}$/.test(smsCode.trim())) throw new Error('请输入正确验证码')
      if (needsNewPassword) {
        if (!passwordIsUsable(password)) throw new Error(passwordOnlyWhitespace ? '密码不能全为空格' : passwordTooLong ? '密码过长，请减少字符' : '密码需为 8-64 位')
        if (password !== passwordConfirm) throw new Error('两次输入的密码不一致')
      }
      if (effectiveCodeAction === 'reset') {
        await auth.resetPassword(cleanPhone, smsCode.trim(), password, passwordConfirm)
        markChallengeRegistered(cleanPhone)
      } else {
        await auth.loginWithPhone(
          cleanPhone,
          smsCode.trim(),
          effectiveCodeAction === 'register' ? password : undefined,
          effectiveCodeAction === 'register' ? passwordConfirm : undefined,
        )
        markChallengeRegistered(cleanPhone)
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '登录失败')
    } finally {
      setSubmitting(false)
    }
  }

  const submitText = mode === 'password'
    ? '登录'
    : effectiveCodeAction === 'register'
      ? '注册并登录'
      : effectiveCodeAction === 'reset'
        ? '重置并登录'
        : '登录'

  return (
    <div className="auth-overlay" onMouseDown={() => { if (!submitting) auth.closeAuth() }}>
      <form
        className="auth-modal"
        onSubmit={submit}
        onMouseDown={(event) => event.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-labelledby="auth-modal-title"
        aria-busy={submitting || sendingCode}
      >
        <button className="auth-modal__close" type="button" onClick={auth.closeAuth} aria-label="关闭" disabled={submitting}>
          <X size={18} />
        </button>

        <header className="auth-modal__header">
          <BrandLogo className="auth-modal__logo" />
          <h2 id="auth-modal-title">登录 Vibelo</h2>
        </header>

        <div className="auth-modal__tabs" role="tablist" aria-label="登录方式">
          <button
            type="button"
            role="tab"
            aria-selected={mode === 'code'}
            className={mode === 'code' ? 'is-active' : undefined}
            onClick={() => switchMode('code')}
            disabled={sendingCode || submitting}
          >
            验证码登录
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={mode === 'password'}
            className={mode === 'password' ? 'is-active' : undefined}
            onClick={() => switchMode('password')}
            disabled={sendingCode || submitting}
          >
            密码登录
          </button>
        </div>

        <div className="auth-modal__fields">
          <label className="auth-modal__field">
            <span>手机号</span>
            <div className="auth-modal__phone-control">
              <input className="auth-modal__country-code" value="+86" readOnly aria-label="国家区号" tabIndex={-1} />
              <i aria-hidden="true" />
              <Phone size={18} aria-hidden="true" />
              <input
                value={phone}
                onChange={(event) => handlePhoneChange(event.target.value)}
                placeholder="请输入手机号"
                aria-label="手机号"
                autoComplete="tel-national"
                inputMode="numeric"
                maxLength={11}
                autoFocus
                disabled={sendingCode || submitting}
              />
            </div>
          </label>

          {mode === 'code' && (
            <label className="auth-modal__field">
              <span>验证码</span>
              <div className="auth-modal__code-control">
                <MessageSquare size={18} aria-hidden="true" />
                <input
                  value={smsCode}
                  onChange={(event) => setSmsCode(event.target.value.replace(/\D/g, '').slice(0, 8))}
                  placeholder="请输入验证码"
                  aria-label="短信验证码"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                />
                <button type="button" onClick={() => void sendCode()} disabled={sendingCode || cooldown > 0}>
                  {sendingCode ? <Loader2 size={16} aria-hidden="true" /> : cooldown > 0 ? `${cooldown}s` : '获取验证码'}
                </button>
              </div>
            </label>
          )}

          {(mode === 'password' || needsNewPassword) && (
            <label className="auth-modal__field">
              <span>{mode === 'password' ? '密码' : '设置密码'}</span>
              <div className="auth-modal__password-control">
                <KeyRound size={18} aria-hidden="true" />
                <input
                  value={password}
                  onChange={(event) => setPassword(event.target.value.slice(0, PASSWORD_MAX_LENGTH))}
                  placeholder={mode === 'password' ? '请输入密码' : '8-64 位密码'}
                  aria-label={mode === 'password' ? '密码' : '设置密码'}
                  type={showPassword ? 'text' : 'password'}
                  autoComplete={mode === 'password' ? 'current-password' : 'new-password'}
                  minLength={mode === 'password' ? 1 : PASSWORD_MIN_LENGTH}
                  maxLength={PASSWORD_MAX_LENGTH}
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

          {needsNewPassword && (
            <label className="auth-modal__field">
              <span>确认密码</span>
              <div className="auth-modal__password-control">
                <KeyRound size={18} aria-hidden="true" />
                <input
                  value={passwordConfirm}
                  onChange={(event) => setPasswordConfirm(event.target.value.slice(0, PASSWORD_MAX_LENGTH))}
                  placeholder="再次输入密码"
                  aria-label="确认密码"
                  type={showPassword ? 'text' : 'password'}
                  autoComplete="new-password"
                  minLength={PASSWORD_MIN_LENGTH}
                  maxLength={PASSWORD_MAX_LENGTH}
                />
                <span className="auth-modal__control-spacer" aria-hidden="true" />
              </div>
            </label>
          )}
        </div>

        {passwordTooLong && <p className="auth-modal__validation" role="status">密码过长，请减少字符</p>}
        {passwordOnlyWhitespace && <p className="auth-modal__validation" role="status">密码不能全为空格</p>}
        {passwordsMismatch && <p className="auth-modal__validation" role="status">两次输入的密码不一致</p>}

        {mode === 'code' && account === 'new' && codeAction === 'login' && (
          <p className="auth-modal__flow-note">首次登录，请设置密码</p>
        )}
        {mode === 'code' && (account !== 'new' || codeAction === 'reset') && (
          <button className="auth-modal__secondary" type="button" onClick={toggleReset} disabled={sendingCode || submitting}>
            {codeAction === 'reset' ? '返回验证码登录' : '忘记密码？短信重置'}
          </button>
        )}
        {mode === 'password' && (
          <button className="auth-modal__secondary" type="button" onClick={beginReset} disabled={sendingCode || submitting}>
            忘记密码？短信重置
          </button>
        )}
        {mockCode && <p className="auth-modal__hint">本地验证码：{mockCode}</p>}
        {error && <p className="auth-modal__error" role="alert" aria-live="polite">{error}</p>}

        <button className="auth-modal__submit" type="submit" disabled={!canSubmit}>
          {submitting && <Loader2 size={17} aria-hidden="true" />}
          {submitText}
        </button>
      </form>
    </div>
  )
}
