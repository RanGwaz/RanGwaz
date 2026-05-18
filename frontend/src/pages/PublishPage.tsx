/** Creator page for publishing image posts. */
import { ArrowLeft, Check, ImagePlus, Plus, Send, X } from 'lucide-react'
import { ChangeEvent, FormEvent, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../AuthContext'
import { api } from '../services/api'
import type { TopicView, UploadResponse } from '../types'

export function PublishPage() {
  const auth = useAuth()
  const navigate = useNavigate()
  const [title, setTitle] = useState('')
  const [content, setContent] = useState('')
  const [topicInput, setTopicInput] = useState('')
  const [topics, setTopics] = useState<string[]>(['旅行碎片'])
  const [assets, setAssets] = useState<UploadResponse[]>([])
  const [suggestions, setSuggestions] = useState<TopicView[]>([])
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    api.trendingTopics(10).then(setSuggestions).catch(() => undefined)
  }, [])

  useEffect(() => {
    if (!auth.user) auth.openAuth()
  }, [auth])

  async function selectFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    if (!file) return
    const response = await api.uploadImage(file)
    setAssets((current) => [...current, response])
  }

  function addTopic(raw = topicInput) {
    const topic = raw.trim().replace(/^#+/, '')
    if (!topic || topics.includes(topic)) return
    setTopics((current) => [...current, topic].slice(0, 8))
    setTopicInput('')
  }

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (!auth.user) {
      auth.openAuth()
      return
    }
    setSaving(true)
    try {
      const created = await api.createPost({
        title: title.trim() || '未命名作品',
        content,
        postType: 'image',
        tags: topics,
        topics,
        imageUrls: assets.map((asset) => asset.fileUrl),
        assets: assets.map((asset, index) => ({ ...asset, sortOrder: index })),
      })
      navigate(`/posts/${created.id}`)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="publish-page">
      <aside className="publish-page__left">
        <section>
          <h3>草稿箱 <em>(0)</em></h3>
          <p>开始编辑后会自动保存在本地，后续可以继续扩展草稿能力。</p>
          <button type="button"><Plus size={16} />新建草稿</button>
        </section>
        <footer><Check size={16} />正在编辑中</footer>
      </aside>
      <form className="publish-page__editor" onSubmit={submit}>
        <header>
          <button type="button" onClick={() => navigate(-1)}><ArrowLeft size={18} /></button>
          <h1>新建发布</h1>
          <span><Check size={15} />已保存</span>
        </header>
        <section className="publish-page__card">
          <h2>基础信息</h2>
          <label>
            <strong>作品描述</strong>
            <div className="publish-page__description">
              <input value={title} maxLength={40} onChange={(event) => setTitle(event.target.value)} placeholder="添加作品标题" />
              <div className="publish-page__topics">
                {topics.map((topic) => <span key={topic}>#{topic}<button type="button" onClick={() => setTopics((current) => current.filter((item) => item !== topic))}><X size={12} /></button></span>)}
              </div>
              <textarea value={content} onChange={(event) => setContent(event.target.value)} placeholder="分享图片背后的故事..." />
              <div className="publish-page__topic-entry">
                <input value={topicInput} onChange={(event) => setTopicInput(event.target.value)} placeholder="# 添加话题" />
                <button type="button" onClick={() => addTopic()}>添加</button>
              </div>
            </div>
          </label>
          <label>
            <strong>上传图片</strong>
            <div className="publish-page__uploads">
              {assets.map((asset, index) => (
                <article key={asset.objectKey}>
                  <img src={asset.fileUrl} alt="" />
                  <button type="button" onClick={() => setAssets((current) => current.filter((_, i) => i !== index))}><X size={14} /></button>
                </article>
              ))}
              <span>
                <ImagePlus size={24} />
                上传图片
                <input type="file" accept="image/*" onChange={selectFile} />
              </span>
            </div>
          </label>
          <div className="publish-page__suggestions">
            <strong>推荐话题</strong>
            {suggestions.slice(0, 8).map((topic) => <button key={topic.id} type="button" onClick={() => addTopic(topic.name)}>#{topic.name}</button>)}
          </div>
        </section>
        <footer className="publish-page__bottom">
          <button type="button" onClick={() => navigate('/home')}>取消</button>
          <button className="is-primary" type="submit" disabled={saving}><Send size={17} />{saving ? '发布中...' : '发布'}</button>
        </footer>
      </form>
      <aside className="publish-page__preview">
        <section>
          <div className="publish-phone">
            <div className="publish-phone__status"><span>9:41</span><b /></div>
            <article>
              {assets[0] ? <img src={assets[0].fileUrl} alt="" /> : <div className="publish-phone__empty">图片预览</div>}
              <div>
                <h3>{title || '未命名作品'}</h3>
                <p>{content || '内容为空时，这里会显示简短占位文案。'}</p>
                <footer>{topics.map((topic) => <span key={topic}>#{topic}</span>)}</footer>
              </div>
            </article>
          </div>
        </section>
      </aside>
    </div>
  )
}
