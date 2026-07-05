/** Simple creator page for publishing images. */
import { ArrowLeft, ImagePlus, Loader2, Plus, Save, Send, X } from 'lucide-react'
import { ChangeEvent, DragEvent, FormEvent, KeyboardEvent, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../AuthContext'
import { api } from '../services/api'
import type { TagView, UploadResponse } from '../types'

const DRAFT_KEY = 'rangwaz-image-draft'
const MAX_ASSETS = 9
const MAX_TAGS = 12

interface PublishDraft {
  content?: string
  selectedTags?: string[]
  title?: string
}

function cleanLabel(raw: string) {
  return raw.trim().replace(/^#+/, '').replace(/\s+/g, ' ')
}

function hasLabel(values: string[], value: string) {
  return values.some((item) => item.toLowerCase() === value.toLowerCase())
}

function uniqueLabels(values: string[]) {
  return values.reduce<string[]>((result, value) => {
    const label = cleanLabel(value)
    if (label && !hasLabel(result, label)) result.push(label)
    return result
  }, [])
}

function hashTagsFromText(value: string) {
  return Array.from(value.matchAll(/#([\p{L}\p{N}_\-\u4e00-\u9fa5]+)/gu), (match) => match[1])
}

export function PublishPage() {
  const auth = useAuth()
  const navigate = useNavigate()
  const [title, setTitle] = useState('')
  const [content, setContent] = useState('')
  const [tagInput, setTagInput] = useState('')
  const [selectedTags, setSelectedTags] = useState<string[]>([])
  const [assets, setAssets] = useState<UploadResponse[]>([])
  const [tagSuggestions, setTagSuggestions] = useState<TagView[]>([])
  const [saving, setSaving] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [draggingFiles, setDraggingFiles] = useState(false)
  const [error, setError] = useState('')
  const dragDepthRef = useRef(0)

  const publishTags = useMemo(
    () => uniqueLabels([...selectedTags, ...hashTagsFromText(title), ...hashTagsFromText(content)]).slice(0, MAX_TAGS),
    [content, selectedTags, title],
  )
  const visibleSuggestions = useMemo(
    () => tagSuggestions.filter((tag) => !hasLabel(publishTags, tag.name)).slice(0, 18),
    [publishTags, tagSuggestions],
  )

  useEffect(() => {
    api.imageTags(undefined, 36).then(setTagSuggestions).catch(() => undefined)
  }, [])

  useEffect(() => {
    if (auth.ready && !auth.user) auth.openAuth()
  }, [auth.ready, auth.user, auth.openAuth])

  useEffect(() => {
    const saved = localStorage.getItem(DRAFT_KEY)
    if (!saved) return
    try {
      const draft = JSON.parse(saved) as PublishDraft
      setTitle(draft.title || '')
      setContent(draft.content || '')
      setSelectedTags(draft.selectedTags || [])
    } catch {
      localStorage.removeItem(DRAFT_KEY)
    }
  }, [])

  useEffect(() => {
    const draft: PublishDraft = { content, selectedTags, title }
    localStorage.setItem(DRAFT_KEY, JSON.stringify(draft))
  }, [content, selectedTags, title])

  function addTags(raw: string) {
    const labels = uniqueLabels(raw.split(/[\s,，]+/))
    if (!labels.length) return
    setSelectedTags((current) => uniqueLabels([...current, ...labels]).slice(0, MAX_TAGS))
  }

  function removeTag(label: string) {
    setSelectedTags((current) => current.filter((item) => item.toLowerCase() !== label.toLowerCase()))
  }

  function handleTagChange(value: string) {
    if (/[\s,，]$/.test(value)) {
      addTags(value)
      setTagInput('')
      return
    }
    setTagInput(value)
  }

  function handleTagKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (!tagInput.trim()) return
    if (event.key === 'Enter' || event.key === 'Tab') {
      event.preventDefault()
      addTags(tagInput)
      setTagInput('')
    }
  }

  async function uploadFiles(files: File[]) {
    const candidates = files.filter((file) => file.type.startsWith('image/')).slice(0, Math.max(0, MAX_ASSETS - assets.length))
    if (!candidates.length) return
    setUploading(true)
    setError('')
    try {
      const uploaded = await Promise.all(candidates.map((file) => api.uploadImage(file)))
      setAssets((current) => [...current, ...uploaded].slice(0, MAX_ASSETS))
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '图片上传失败')
    } finally {
      setUploading(false)
    }
  }

  async function selectFile(event: ChangeEvent<HTMLInputElement>) {
    await uploadFiles(Array.from(event.target.files || []))
    event.target.value = ''
  }

  function isFileDrag(event: DragEvent<HTMLElement>) {
    return Array.from(event.dataTransfer.types).includes('Files')
  }

  function enterDropZone(event: DragEvent<HTMLElement>) {
    event.preventDefault()
    if (!isFileDrag(event)) return
    dragDepthRef.current += 1
    event.dataTransfer.dropEffect = 'copy'
    setDraggingFiles(true)
  }

  function overDropZone(event: DragEvent<HTMLElement>) {
    event.preventDefault()
    if (isFileDrag(event)) event.dataTransfer.dropEffect = 'copy'
  }

  function leaveDropZone(event: DragEvent<HTMLElement>) {
    event.preventDefault()
    dragDepthRef.current = Math.max(0, dragDepthRef.current - 1)
    if (dragDepthRef.current === 0) setDraggingFiles(false)
  }

  function dropFiles(event: DragEvent<HTMLElement>) {
    event.preventDefault()
    dragDepthRef.current = 0
    setDraggingFiles(false)
    void uploadFiles(Array.from(event.dataTransfer.files || []))
  }

  function resetDraft() {
    setTitle('')
    setContent('')
    setTagInput('')
    setSelectedTags([])
    setAssets([])
    setError('')
    localStorage.removeItem(DRAFT_KEY)
  }

  async function submit(event: FormEvent) {
    event.preventDefault()
    setError('')
    if (!auth.user) {
      auth.openAuth()
      return
    }
    if (!assets.length) {
      setError('请至少上传一张图片')
      return
    }
    const tags = uniqueLabels([...publishTags, tagInput]).slice(0, MAX_TAGS)
    setSaving(true)
    try {
      const created = await api.createImage({
        title: title.trim(),
        content,
        postType: 'image',
        tags,
        topics: [],
        imageUrls: assets.map((asset) => asset.fileUrl),
        assets: assets.map((asset, index) => ({ ...asset, sortOrder: index })),
      })
      localStorage.removeItem(DRAFT_KEY)
      navigate(`/image/${created.id}`)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '发布失败')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="publish-page publish-page--simple">
      <form className="publish-simple" onSubmit={submit}>
        <header className="publish-simple__top">
          <button type="button" onClick={() => navigate(-1)} aria-label="返回"><ArrowLeft size={18} /></button>
          <h1>发布图片</h1>
          <span><Save size={15} />自动保存</span>
        </header>

        <section
          className={draggingFiles ? 'publish-simple__panel publish-simple__panel--drop is-dragging' : 'publish-simple__panel publish-simple__panel--drop'}
          onDragEnter={enterDropZone}
          onDragLeave={leaveDropZone}
          onDragOver={overDropZone}
          onDrop={dropFiles}
        >
          <div className="publish-simple__uploads">
            {assets.map((asset, index) => (
              <article key={`${asset.objectKey}-${index}`}>
                <img src={asset.thumbUrl || asset.fileUrl} alt="" />
                <span>{index === 0 ? '封面' : `#${index + 1}`}</span>
                <button type="button" onClick={() => setAssets((current) => current.filter((_, itemIndex) => itemIndex !== index))} aria-label="移除图片">
                  <X size={14} />
                </button>
              </article>
            ))}
            {assets.length < MAX_ASSETS && (
              <label className={uploading ? 'is-uploading' : undefined}>
                {uploading ? <Loader2 size={24} /> : <ImagePlus size={24} />}
                <strong>{uploading ? '上传中' : '上传图片'}</strong>
                <input type="file" accept="image/*" multiple onChange={selectFile} />
              </label>
            )}
          </div>
        </section>

        <section className="publish-simple__panel publish-simple__fields">
          <input value={title} maxLength={80} onChange={(event) => setTitle(event.target.value)} placeholder="标题" />
          <textarea value={content} maxLength={5000} onChange={(event) => setContent(event.target.value)} placeholder="描述" />
        </section>

        <section className="publish-simple__panel publish-simple__tags">
          <div className="publish-simple__tag-input">
            <span>#</span>
            <input
              value={tagInput}
              onBlur={() => {
                addTags(tagInput)
                setTagInput('')
              }}
              onChange={(event) => handleTagChange(event.target.value)}
              onKeyDown={handleTagKeyDown}
              placeholder="输入标签"
            />
          </div>
          {publishTags.length > 0 && (
            <div className="publish-simple__tag-row">
              {publishTags.map((tag) => (
                <button key={tag} type="button" onClick={() => removeTag(tag)}>
                  #{tag}<X size={12} />
                </button>
              ))}
            </div>
          )}
          {visibleSuggestions.length > 0 && (
            <div className="publish-simple__tag-row publish-simple__tag-row--suggestions">
              {visibleSuggestions.map((tag) => (
                <button key={tag.id} type="button" onClick={() => addTags(tag.name)}>#{tag.name}</button>
              ))}
            </div>
          )}
        </section>

        <footer className="publish-simple__bottom">
          {error && <p>{error}</p>}
          <div>
            <button type="button" onClick={resetDraft}><Plus size={16} />清空</button>
            <button className="is-primary" type="submit" disabled={saving || uploading}>
              {saving ? <Loader2 size={17} /> : <Send size={17} />}
              {saving ? '发布中' : '发布'}
            </button>
          </div>
        </footer>
      </form>
    </div>
  )
}
