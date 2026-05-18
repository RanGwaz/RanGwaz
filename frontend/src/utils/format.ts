/** Formatting helpers shared by the image-site pages. */
import type { PostView } from '../types'

export function imageUrl(url?: string | null) {
  return url || 'https://picsum.photos/seed/empty-image/640/840'
}

export function postCover(post: PostView, index = 0) {
  return imageUrl(post.assets?.[index]?.fileUrl || post.coverUrl || post.thumbUrl || post.images?.[0]?.url)
}

export function avatarUrl(url?: string | null) {
  return imageUrl(url || 'https://api.dicebear.com/9.x/adventurer/svg?seed=user')
}

export function aspectRatio(post: PostView) {
  const asset = post.assets?.find((item) => Number(item.width) > 0 && Number(item.height) > 0)
  if (asset?.width && asset.height) return `${asset.width} / ${asset.height}`
  const ratios = ['3 / 4.2', '3 / 3.6', '3 / 4.8', '3 / 3.9', '3 / 4.5', '3 / 5.1']
  return ratios[Math.abs(post.id) % ratios.length]
}

export function relativeTime(iso?: string) {
  if (!iso) return ''
  const diff = Date.now() - new Date(iso).getTime()
  if (diff < 60_000) return '刚刚'
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}分钟前`
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}小时前`
  if (diff < 604_800_000) return `${Math.floor(diff / 86_400_000)}天前`
  return new Date(iso).toLocaleDateString('zh-CN')
}

export function countText(value?: number | null) {
  const n = Number(value || 0)
  if (n >= 10000) return `${(n / 10000).toFixed(n >= 100000 ? 0 : 1)}w`
  if (n >= 1000) return `${(n / 1000).toFixed(1).replace('.0', '')}k`
  return String(Math.max(0, n))
}

export function distributePosts(posts: PostView[], count: number) {
  const safeCount = Math.max(1, count)
  const columns = Array.from({ length: safeCount }, () => ({ height: 0, records: [] as PostView[] }))
  posts.forEach((post) => {
    const [w, h] = aspectRatio(post).split('/').map((item) => Number(item.trim()))
    const score = Number.isFinite(w) && Number.isFinite(h) && w > 0 ? h / w : 1.35
    const target = columns.reduce((min, column) => (column.height < min.height ? column : min), columns[0])
    target.records.push(post)
    target.height += score + 0.4
  })
  return columns.map((column) => column.records)
}
