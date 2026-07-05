/** Dedicated profile editing page. */
import { Camera, Check, ChevronLeft, FileText, Image as ImageIcon, Loader2, UploadCloud, UserRound, X } from 'lucide-react'
import { ChangeEvent, FormEvent, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../AuthContext'
import { api } from '../services/api'
import type { UploadResponse } from '../types'
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

export function ProfileEditPage() {
  const auth = useAuth()
  const navigate = useNavigate()
  const [draft, setDraft] = useState<ProfileDraft>({ avatarUrl: '', backgroundUrl: '', bio: '', nickname: '' })
  const [saving, setSaving] = useState(false)
  const [avatarUploading, setAvatarUploading] = useState(false)
  const [backgroundUploading, setBackgroundUploading] = useState(false)
  const [error, setError] = useState('')

  const uploading = avatarUploading || backgroundUploading
  const displayName = draft.nickname.trim() || auth.user?.nickname || ''
  const displayBio = draft.bio.trim() || '用镜头记录生活的细节与美好。'
  const disabled = saving || uploading

  useEffect(() => {
    if (!auth.ready) return
    if (!auth.user) {
      auth.openAuth()
      navigate('/home', { replace: true })
      return
    }

    setDraft({
      avatarUrl: auth.user.avatarUrl || '',
      backgroundUrl: auth.user.backgroundUrl || '',
      bio: auth.user.bio || '',
      nickname: auth.user.nickname || '',
    })
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
    try {
      const uploaded = await api.uploadImage(file)
      const url = uploadedUrl(uploaded)
      if (!url) throw new Error('图片上传成功，但没有返回可用地址')
      setDraft((current) => target === 'avatar'
        ? { ...current, avatarUrl: url }
        : { ...current, backgroundUrl: url })
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
    try {
      const review = await api.updateProfile({
        avatarUrl: draft.avatarUrl.trim(),
        backgroundUrl: draft.backgroundUrl.trim(),
        bio: draft.bio.trim(),
        nickname: draft.nickname.trim(),
      })
      auth.updateUser({
        ...auth.user,
        avatarUrl: review.avatarUrl || draft.avatarUrl.trim(),
        backgroundUrl: review.backgroundUrl || draft.backgroundUrl.trim(),
        bio: review.bio || draft.bio.trim(),
        nickname: review.nickname || draft.nickname.trim(),
      })
      navigate('/profile', { replace: true })
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

  return (
    <div className="profile-edit-page">
      <header className="profile-edit-page__topbar">
        <button className="profile-edit-page__back" type="button" onClick={() => navigate('/profile')}>
          <ChevronLeft size={18} />
          返回
        </button>
        <div className="profile-edit-page__title">
          <h1>编辑资料</h1>
          <span>@{auth.user.username}</span>
        </div>
        <div className="profile-edit-page__commands">
          <button type="button" onClick={() => navigate('/profile')} disabled={saving}>
            <X size={16} />
            取消
          </button>
          <button className="is-primary" type="submit" form="profile-edit-form" disabled={disabled}>
            {saving ? <Loader2 size={16} /> : <Check size={16} />}
            保存
          </button>
        </div>
      </header>

      <main className="profile-edit-page__workspace">
        <section className="profile-edit-page__preview-panel">
          <div className="profile-edit-page__cover-stage">
            <img src={draft.backgroundUrl || DEFAULT_PROFILE_BACKGROUND} alt="" />
            <label className="profile-edit-page__cover-upload">
              {backgroundUploading ? <Loader2 size={16} /> : <UploadCloud size={16} />}
              更换背景
              <input type="file" accept="image/*" onChange={(event) => void uploadProfileImage('background', event)} disabled={disabled} />
            </label>
          </div>

          <div className="profile-edit-page__profile-card">
            <div className="profile-edit-page__avatar-shell">
              <img src={avatarUrl(draft.avatarUrl)} alt="" />
              <label aria-label="更换头像">
                {avatarUploading ? <Loader2 size={15} /> : <Camera size={15} />}
                <input type="file" accept="image/*" onChange={(event) => void uploadProfileImage('avatar', event)} disabled={disabled} />
              </label>
            </div>
            <div className="profile-edit-page__profile-copy">
              <strong>{displayName}</strong>
              <p>{displayBio}</p>
            </div>
          </div>
        </section>

        <form id="profile-edit-form" className="profile-edit-page__editor-panel" onSubmit={saveProfile}>
          <section className="profile-edit-page__section">
            <h2>图片</h2>
            <div className="profile-edit-page__media-grid">
              <label className="profile-edit-page__media-tile">
                <span>{avatarUploading ? <Loader2 size={19} /> : <Camera size={19} />}</span>
                <strong>{avatarUploading ? '头像上传中' : '上传头像'}</strong>
                <input type="file" accept="image/*" onChange={(event) => void uploadProfileImage('avatar', event)} disabled={disabled} />
              </label>
              <label className="profile-edit-page__media-tile">
                <span>{backgroundUploading ? <Loader2 size={19} /> : <ImageIcon size={19} />}</span>
                <strong>{backgroundUploading ? '背景上传中' : '上传背景'}</strong>
                <input type="file" accept="image/*" onChange={(event) => void uploadProfileImage('background', event)} disabled={disabled} />
              </label>
            </div>
          </section>

          <section className="profile-edit-page__section">
            <h2>资料</h2>
            <label className="profile-edit-page__field">
              <span><UserRound size={16} />昵称</span>
              <input value={draft.nickname} maxLength={24} onChange={(event) => setDraft({ ...draft, nickname: event.target.value })} placeholder="请输入昵称" />
            </label>
            <label className="profile-edit-page__field">
              <span><FileText size={16} />简介</span>
              <textarea value={draft.bio} maxLength={120} onChange={(event) => setDraft({ ...draft, bio: event.target.value })} placeholder="介绍一下自己" />
              <em>{draft.bio.length}/120</em>
            </label>
          </section>

          {error && <p className="profile-edit-page__error">{error}</p>}
        </form>
      </main>
    </div>
  )
}
