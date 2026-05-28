/** Formatting helpers shared by the image-site pages. */
import type { ImageView } from '../types'

export function imageUrl(url?: string | null) {
  return url || 'https://picsum.photos/seed/empty-image/640/840'
}

export function imageOriginal(image: ImageView, index = 0) {
  const asset = image.assets?.[index]
  return imageUrl(asset?.fileUrl || image.coverUrl || image.images?.[0]?.url || image.thumbUrl || asset?.thumbUrl)
}

export function imageThumbnail(image: ImageView, index = 0) {
  const asset = image.assets?.[index]
  return imageUrl(asset?.thumbUrl || image.thumbUrl || image.coverUrl || asset?.fileUrl || image.images?.[0]?.url)
}

export function imageCover(image: ImageView, index = 0) {
  return imageOriginal(image, index)
}

export function avatarUrl(url?: string | null) {
  return imageUrl(url || 'https://api.dicebear.com/9.x/adventurer/svg?seed=user')
}

export function aspectRatio(image: ImageView) {
  const asset = image.assets?.find((item) => Number(item.width) > 0 && Number(item.height) > 0)
  if (asset?.width && asset.height) return `${asset.width} / ${asset.height}`
  const ratios = ['3 / 4.2', '3 / 3.6', '3 / 4.8', '3 / 3.9', '3 / 4.5', '3 / 5.1']
  return ratios[Math.abs(image.id) % ratios.length]
}

export function relativeTime(iso?: string) {
  if (!iso) return ''
  const diff = Date.now() - new Date(iso).getTime()
  if (!Number.isFinite(diff)) return ''
  if (diff < 60_000) return '\u521a\u521a'
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}\u5206\u949f\u524d`
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}\u5c0f\u65f6\u524d`
  if (diff < 604_800_000) return `${Math.floor(diff / 86_400_000)}\u5929\u524d`
  return new Date(iso).toLocaleDateString('zh-CN')
}

export function countText(value?: number | null) {
  const n = Number(value || 0)
  if (n >= 10000) return `${(n / 10000).toFixed(n >= 100000 ? 0 : 1)}\u4e07`
  if (n >= 1000) return `${(n / 1000).toFixed(1).replace('.0', '')}k`
  return String(Math.max(0, n))
}

export function distributeImages(images: ImageView[], count: number) {
  const safeCount = Math.max(1, count)
  const columns = Array.from({ length: safeCount }, () => ({ height: 0, records: [] as ImageView[] }))
  images.forEach((image) => {
    const [w, h] = aspectRatio(image).split('/').map((item) => Number(item.trim()))
    const score = Number.isFinite(w) && Number.isFinite(h) && w > 0 ? h / w : 1.35
    const target = columns.reduce((min, column) => (column.height < min.height ? column : min), columns[0])
    target.records.push(image)
    target.height += score + 0.4
  })
  return columns.map((column) => column.records)
}
