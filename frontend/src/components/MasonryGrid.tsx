/** Shared responsive masonry grid for post cards across feed-like pages. */
import { CSSProperties, useLayoutEffect, useMemo, useRef, useState } from 'react'
import type { PostView } from '../types'
import { aspectRatio } from '../utils/format'
import { PostCard } from './PostCard'

const MASONRY_GAP = 16
const MASONRY_TARGET_WIDTH = 236
const MASONRY_MAX_COLUMNS = 12
const MASONRY_CARD_CHROME = 82

interface MasonryGridProps {
  posts: PostView[]
  liked?: Set<number>
  emptyLabel?: string
  onOpen: (post: PostView) => void
  onLike?: (post: PostView) => void
}

interface MasonryItem {
  height: number
  post: PostView
  width: number
  x: number
  y: number
}

/** Clamp a numeric value between inclusive bounds. */
function clampNumber(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value))
}

/** Resolve a fluid Pinterest-like column model from container width. */
function resolveMasonry(width: number) {
  const columnCount = clampNumber(Math.floor((width + MASONRY_GAP) / (MASONRY_TARGET_WIDTH + MASONRY_GAP)), 1, MASONRY_MAX_COLUMNS)
  const columnWidth = (width - (columnCount - 1) * MASONRY_GAP) / columnCount
  return { columnCount, columnWidth }
}

/** Estimate the final card height for absolute masonry packing. */
function estimateHeight(post: PostView, columnWidth: number) {
  const [w, h] = aspectRatio(post).split('/').map((item) => Number(item.trim()))
  const ratio = Number.isFinite(w) && Number.isFinite(h) && w > 0 ? h / w : 1.35
  return Math.max(136, columnWidth * ratio) + MASONRY_CARD_CHROME
}

/** Pack cards into shortest columns while preserving a stable visual order. */
function packPosts(posts: PostView[], columnCount: number, columnWidth: number) {
  const heights = Array.from({ length: Math.max(1, columnCount) }, () => 0)
  const items: MasonryItem[] = posts.map((post) => {
    const height = estimateHeight(post, columnWidth)
    const columnIndex = heights.reduce((min, value, index) => (value < heights[min] ? index : min), 0)
    const x = columnIndex * (columnWidth + MASONRY_GAP)
    const y = heights[columnIndex]
    heights[columnIndex] += height + MASONRY_GAP
    return { height, post, width: columnWidth, x, y }
  })
  return { height: Math.max(...heights, 1), items }
}

export function MasonryGrid({ posts, liked, emptyLabel = '暂无内容', onOpen, onLike }: MasonryGridProps) {
  const rootRef = useRef<HTMLDivElement | null>(null)
  const [metrics, setMetrics] = useState({ columnCount: 1, columnWidth: MASONRY_TARGET_WIDTH, ready: false })
  const layout = useMemo(() => packPosts(posts, metrics.columnCount, metrics.columnWidth), [metrics.columnCount, metrics.columnWidth, posts])

  useLayoutEffect(() => {
    const target = rootRef.current
    if (!target) return
    let frame = 0
    const update = () => {
      cancelAnimationFrame(frame)
      frame = requestAnimationFrame(() => {
        if (!target.clientWidth) return
        setMetrics({ ...resolveMasonry(target.clientWidth), ready: true })
      })
    }
    update()
    const observer = new ResizeObserver(update)
    observer.observe(target)
    window.addEventListener('resize', update)
    return () => {
      cancelAnimationFrame(frame)
      observer.disconnect()
      window.removeEventListener('resize', update)
    }
  }, [])

  if (!posts.length) {
    return <div ref={rootRef} className="masonry-grid masonry-grid--empty">{emptyLabel}</div>
  }

  return (
    <div ref={rootRef} className={metrics.ready ? 'masonry-grid' : 'masonry-grid is-measuring'}>
      {metrics.ready ? (
        <div className="masonry-grid__canvas" style={{ height: layout.height } as CSSProperties}>
          {layout.items.map((item) => (
            <div
              className="masonry-grid__item"
              key={item.post.id}
              style={{ transform: `translate3d(${item.x}px,${item.y}px,0)`, width: item.width } as CSSProperties}
            >
              <PostCard post={item.post} liked={liked?.has(item.post.id)} onOpen={onOpen} onLike={onLike} />
            </div>
          ))}
        </div>
      ) : <div className="masonry-grid__skeleton" />}
    </div>
  )
}
