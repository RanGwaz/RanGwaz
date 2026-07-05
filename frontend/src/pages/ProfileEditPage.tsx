/** Dedicated profile editing page with review-aware submission. */
import { Bell, Camera, Check, ChevronLeft, CircleAlert, Clock3, FileText, ImagePlus, Loader2, ShieldCheck, UserRound, X } from 'lucide-react'
import { ChangeEvent, FormEvent, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../AuthContext'
import { api } from '../services/api'
import type { ProfileReviewView, UploadResponse } from '../types'
import { avatarUrl } from '../utils/format'

const DEFAULT_PROFILE_BACKGROUND = '/default-background.jpg'
const MAX_PROFILE_IMAGE_SIZE = 12 * 1024 * 1024

interface ProfileDraft {
  avatarUrl: string
  backgroundUrl: string
  bio: string
  nickname: string
}

type UploadTarget = 'avatar' | 'background'

function uploadedUrl(uploaded: UploadResponse) {
  return uploaded.fileUrl || uploaded.thumbUrl || ''
}

function reviewLabel(status?: string) {
  if (status === 'REJECTED') return '安全检测未通过'
  if (status === 'PUBLISHED' || status === 'APPROVED') return '安全检测通过'
  if (status === 'PENDING_REVIEW') return '检测中'
  if (status === 'SUPERSEDED') return '已被新记录替换'
  return '未检测'
}

function reviewTone(status?: string) {
  if (status === 'REJECTED') return 'is-rejected'
  if (status === 'PUBLISHED' || status === 'APPROVED') return 'is-approved'
  return 'is-pending'
}

function formatTime(value?: string) {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return date.toLocaleString('zh-CN', { hour12: false })
}

export function ProfileEditPage() {
  const auth = useAuth()
  const navigate = useNavigate()
  const [draft, setDraft] = useState<ProfileDraft>({ avatarUrl: '', backgroundUrl: '', bio: '', nickname: '' })
  const [latestReview, setLatestReview] = useState<ProfileReviewView | null>(null)
  const [notice, setNotice] = useState('')
  const [saving, setSaving] = useState(false)
  const [avatarUploading, setAvatarUploading] = useState(false)
  const [backgroundUploading, setBackgroundUploading] = useState(false)
  const [error, setError] = useState('')

  const uploading = avatarUploading || backgroundUploading

  useEffect(() => {
    if (!auth.ready) return
    if (!auth.user) {
      auth.openAuth()
      navigate('/home', { replace: true })
      return
    }

    let cancelled = false
    const baseDraft = {
      avatarUrl: auth.user.avatarUrl || '',
      backgroundUrl: auth.user.backgroundUrl || '',
      bio: auth.user.bio || '',
      nickname: auth.user.nickname || '',
    }
    setDraft(baseDraft)
    api.profileReview().then((review) => {
      if (cancelled) return
      setLatestReview(review)
      if (review?.status === 'PENDING_REVIEW') {
        setDraft({
          avatarUrl: review.avatarUrl ?? baseDraft.avatarUrl,
          backgroundUrl: review.backgroundUrl ?? baseDraft.backgroundUrl,
          bio: review.bio ?? baseDraft.bio,
          nickname: review.nickname ?? baseDraft.nickname,
        })
      }
    }).catch(() => undefined)

    return () => {
      cancelled = true
    }
  }, [auth.ready, auth.user?.id, navigate])

  async function uploadProfileImage(target: UploadTarget, event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file) return
    if (file.type && !file.type.startsWith('image/')) {
      setError('请选择图片文件')
      return
    }
    if (file.size > MAX_PROFILE_IMAGE_SIZE) {
      setError('图片不能超过 12MB')
      return
    }
    if (target === 'avatar') setAvatarUploading(true)
    else setBackgroundUploading(true)
    setError('')
    setNotice('')
    try {
      const uploaded = await api.uploadImage(file)
      const url = uploadedUrl(uploaded)
      if (!url) throw new Error('图片上传成功，但没有返回可用地址')
      setDraft((current) => target === 'avatar'
        ? { ...current, avatarUrl: url }
        : { ...current, backgroundUrl: url })
      setNotice('图片已完成上传，系统会在上传阶段自动完成安全检测。')
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '图片上传失败')
    } finally {
      if (target === 'avatar') setAvatarUploading(false)
      else setBackgroundUploading(false)
    }
  }

  async function saveProfile(event: FormEvent) {
    event.preventDefault()
    if (!draft.nickname.trim()) {
      setError('昵称不能为空')
      return
    }
    if (!auth.user) return
    setSaving(true)
    setError('')
    setNotice('')
    try {
      const review = await api.updateProfile({
        avatarUrl: draft.avatarUrl.trim(),
        backgroundUrl: draft.backgroundUrl.trim(),
        bio: draft.bio.trim(),
        nickname: draft.nickname.trim(),
      })
      setLatestReview(review)
      auth.updateUser({
        ...auth.user,
        avatarUrl: review.avatarUrl || draft.avatarUrl.trim(),
        backgroundUrl: review.backgroundUrl || draft.backgroundUrl.trim(),
        bio: review.bio || draft.bio.trim(),
        nickname: review.nickname || draft.nickname.trim(),
      })
      setNotice('资料已完成自动安全检测并保存到公开主页。')
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '保存失败')
    } finally {
      setSaving(false)
    }
  }

  if (!auth.ready || !auth.user) {
    return (
      <div className="profile-edit-page">
        <section className="profile-page__loading">
          <Loader2 size={20} />
          正在加载资料...
        </section>
      </div>
    )
  }

  const reviewStatus = latestReview?.status

  return (
    <div className="profile-edit-page">
      <header className="profile-edit-page__head">
        <button type="button" onClick={() => navigate('/profile')}><ChevronLeft size={18} />返回主页</button>
        <span>
          <strong>编辑资料</strong>
          <small>头像、背景、昵称和简介会先自动安全检测，通过后立即更新公开主页。</small>
        </span>
      </header>

      <main className="profile-edit-page__body">
        <section className="profile-edit-page__preview">
          <div className="profile-edit-page__cover-frame">
            <img className="profile-edit-page__cover" src={draft.backgroundUrl || DEFAULT_PROFILE_BACKGROUND} alt="" />
          </div>
          <div className="profile-edit-page__identity">
            <img className="profile-edit-page__avatar" src={avatarUrl(draft.avatarUrl)} alt="" />
            <div>
              <strong>{draft.nickname || auth.user.nickname}</strong>
              <small>{draft.bio || '用镜头记录生活的细节与美好。'}</small>
            </div>
          </div>
          <div className={`profile-edit-page__preview-status ${reviewTone(reviewStatus)}`}>
            <span>{reviewStatus === 'REJECTED' ? <CircleAlert size={15} /> : reviewStatus === 'PUBLISHED' ? <ShieldCheck size={15} /> : <Clock3 size={15} />}</span>
            <strong>{reviewLabel(reviewStatus)}</strong>
            <small>{latestReview ? `最近检测：${formatTime(latestReview.createdAt)}` : '保存资料后将在这里显示检测结果'}</small>
          </div>
        </section>

        <form className="profile-edit-page__form" onSubmit={saveProfile}>
          <section className="profile-edit-page__panel">
            <header>
              <strong>公开资料变更</strong>
              <small>图片上传时会自动检测，文字保存时会自动检测；通过后立即生效。</small>
            </header>

            {latestReview && (
              <section className={`profile-edit-page__review-card ${reviewTone(latestReview.status)}`}>
                <span>{latestReview.status === 'REJECTED' ? <CircleAlert size={18} /> : latestReview.status === 'PUBLISHED' ? <ShieldCheck size={18} /> : <Clock3 size={18} />}</span>
                <div>
                  <strong>{reviewLabel(latestReview.status)}</strong>
                  <small>{latestReview.reviewReason || '最近一次资料保存已完成安全检测。'}</small>
                </div>
                <em>{formatTime(latestReview.reviewedAt || latestReview.createdAt)}</em>
              </section>
            )}

            <div className="profile-edit-page__upload-grid">
              <label className="profile-edit-page__upload-card">
                <span>{avatarUploading ? <Loader2 size={20} /> : <Camera size={20} />}</span>
                <strong>{avatarUploading ? '头像上传中' : '上传头像'}</strong>
                <small>选择本地图片，建议使用方形头像</small>
                <input type="file" accept="image/*" onChange={(event) => void uploadProfileImage('avatar', event)} disabled={avatarUploading || saving} />
              </label>
              <label className="profile-edit-page__upload-card profile-edit-page__upload-card--cover">
                <span>{backgroundUploading ? <Loader2 size={20} /> : <ImagePlus size={20} />}</span>
                <strong>{backgroundUploading ? '背景上传中' : '上传背景图片'}</strong>
                <small>宽幅图片展示效果更好，上传时自动检测</small>
                <input type="file" accept="image/*" onChange={(event) => void uploadProfileImage('background', event)} disabled={backgroundUploading || saving} />
              </label>
            </div>

            <label className="profile-edit-page__field">
              <span><UserRound size={16} />昵称</span>
              <input value={draft.nickname} maxLength={24} onChange={(event) => setDraft({ ...draft, nickname: event.target.value })} placeholder="请输入昵称" />
            </label>

            <label className="profile-edit-page__field">
              <span><FileText size={16} />简介</span>
              <textarea value={draft.bio} maxLength={120} onChange={(event) => setDraft({ ...draft, bio: event.target.value })} placeholder="介绍一下自己" />
              <em>{draft.bio.length}/120</em>
            </label>

            {notice && <p className="profile-edit-page__notice"><Bell size={15} />{notice}</p>}
            {error && <p className="profile-edit-page__error">{error}</p>}

            <footer>
              <button type="button" onClick={() => navigate('/profile')}><X size={16} />取消</button>
              <button className="is-primary" type="submit" disabled={saving || uploading}>
                {saving ? <Loader2 size={16} /> : <Check size={16} />}
                保存资料
              </button>
            </footer>
          </section>
        </form>
      </main>
    </div>
  )
}
