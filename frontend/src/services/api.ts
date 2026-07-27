/** HTTP client and typed API helpers for the React frontend. */
import type {
  ApiResponse,
  AuthTokenResponse,
  CategoryView,
  ClientIpResponse,
  CommentView,
  FollowStatus,
  ImageInteractionStatus,
  ImageView,
  NotificationView,
  PageResponse,
  ProfileReviewView,
  SearchResult,
  SearchSuggestionResponse,
  SmsCodeResponse,
  TagView,
  ToggleResult,
  TopicView,
  UploadResponse,
  UserStats,
  UserSummary,
} from '../types'
import { getVisitorId } from '../utils/visitorIdentity'

const TOKEN_KEY = 'rangwaz-token'
const API_BASE = (import.meta.env.VITE_API_BASE || '').replace(/\/$/, '')

export function getToken() {
  return localStorage.getItem(TOKEN_KEY) || ''
}

export function setToken(token: string) {
  if (token) localStorage.setItem(TOKEN_KEY, token)
  else localStorage.removeItem(TOKEN_KEY)
}

function nonJsonMessage(path: string, response: Response, text: string) {
  const preview = text.trim().slice(0, 180)
  if (preview.toLowerCase().startsWith('<!doctype') || preview.toLowerCase().startsWith('<html')) {
    return `接口 ${path} 返回了页面而不是 JSON。请确认后端 8080 已启动，且 Vite 代理没有失效。`
  }
  return `接口 ${path} 返回了非 JSON 内容：${preview || response.statusText || '空响应'}`
}

function apiPath(path: string) {
  if (!API_BASE) return path
  return `${API_BASE}${path.startsWith('/') ? path : `/${path}`}`
}

async function request<T>(path: string, init: RequestInit = {}) {
  const headers = new Headers(init.headers)
  const token = getToken()
  if (token) headers.set('Authorization', `Bearer ${token}`)
  if (!(init.body instanceof FormData) && init.body !== undefined) headers.set('Content-Type', 'application/json')

  const response = await fetch(apiPath(path), { ...init, headers })
  const text = await response.text()
  let parsed: unknown
  let payload: ApiResponse<T>

  try {
    parsed = text ? JSON.parse(text) as unknown : {
      code: response.ok ? 'OK' : 'EMPTY_RESPONSE',
      data: undefined,
      message: '',
      success: response.ok,
      timestamp: new Date().toISOString(),
    }
  } catch {
    throw new Error(nonJsonMessage(path, response, text))
  }

  if (!parsed || typeof parsed !== 'object' || !('success' in parsed)) {
    throw new Error(`接口 ${path} 返回的 JSON 不是统一 ApiResponse 格式`)
  }
  payload = parsed as ApiResponse<T>

  if (!response.ok || !payload.success) {
    throw new Error(payload.message || `请求失败：${payload.code || response.status}`)
  }
  return payload.data
}

export const api = {
  register(payload: { username: string; password: string; nickname: string }) {
    return request<AuthTokenResponse>('/auth/register', { method: 'POST', body: JSON.stringify(payload) })
  },
  login(payload: { username: string; password: string }) {
    return request<AuthTokenResponse>('/auth/login', { method: 'POST', body: JSON.stringify(payload) })
  },
  sendSmsCode(payload: { phone: string; scene?: string }) {
    return request<SmsCodeResponse>('/auth/sms-code', { method: 'POST', body: JSON.stringify(payload) })
  },
  phoneLogin(payload: { phone: string; code: string; password?: string; passwordConfirm?: string }) {
    return request<AuthTokenResponse>('/auth/phone-login', { method: 'POST', body: JSON.stringify(payload) })
  },
  phonePasswordLogin(payload: { phone: string; password: string }) {
    return request<AuthTokenResponse>('/auth/phone-password-login', { method: 'POST', body: JSON.stringify(payload) })
  },
  logout() {
    return request<void>('/auth/logout', { method: 'POST' })
  },
  me() {
    return request<AuthTokenResponse>('/auth/me')
  },
  homeFeed(page = 1, pageSize = 30, refreshSeed?: string, feedSessionId?: string, visitorId = getVisitorId(), excludeIds: number[] = []) {
    const query = new URLSearchParams({ page: String(page), pageSize: String(pageSize) })
    if (refreshSeed) query.set('refreshSeed', refreshSeed)
    if (feedSessionId) query.set('feedSessionId', feedSessionId)
    if (visitorId) query.set('visitorId', visitorId)
    excludeIds.slice(0, 240).forEach((id) => query.append('excludeIds', String(id)))
    return request<PageResponse<ImageView>>(`/feed?${query.toString()}`)
  },
  similarImages(imageId: number, page = 1, size = 24) {
    return request<PageResponse<ImageView>>(`/feed/images/${imageId}/similar?page=${page}&size=${size}`)
  },
  imageDetail(imageId: number) {
    return request<ImageView>(`/images/${imageId}`)
  },
  clientIp() {
    return request<ClientIpResponse>('/users/client-ip')
  },
  trackImageClick(imageId: number, scene = 'feed', position?: number, visitorId = getVisitorId()) {
    const query = new URLSearchParams({ scene })
    if (position) query.set('position', String(position))
    if (visitorId) query.set('visitorId', visitorId)
    return request<void>(`/images/${imageId}/click?${query.toString()}`, { method: 'POST' })
  },
  trackBehaviors(events: Array<{
    imageId: number
    behaviorType: string
    scene?: string
    position?: number
    duration?: number
    visitorId?: string
    decisionId?: string
    eventId?: string
    source?: string
    score?: number
    occurredAt?: string
  }>, visitorId = getVisitorId()) {
    if (events.length === 0) return Promise.resolve()
    return request<void>('/behaviors/batch', { method: 'POST', body: JSON.stringify({ visitorId, events }) })
  },
  trackImageShare(imageId: number) {
    return request<void>(`/images/${imageId}/share`, { method: 'POST' })
  },
  uploadImage(file: File) {
    const form = new FormData()
    form.append('file', file)
    return request<UploadResponse>('/media/upload', { method: 'POST', body: form })
  },
  toggleLike(imageId: number) {
    return request<ToggleResult>(`/interactions/images/${imageId}/like/toggle`, { method: 'POST' })
  },
  toggleFavorite(imageId: number) {
    return request<ToggleResult>(`/interactions/images/${imageId}/favorite/toggle`, { method: 'POST' })
  },
  commentsPage(imageId: number, page = 1, size = 20) {
    return request<PageResponse<CommentView>>(`/interactions/images/${imageId}/comments/page?page=${page}&size=${size}`)
  },
  comment(imageId: number, content: string, parentCommentId?: number) {
    return request<CommentView>(`/interactions/images/${imageId}/comments`, { method: 'POST', body: JSON.stringify({ content, parentCommentId }) })
  },
  interactionStatuses(imageIds: number[]) {
    const query = new URLSearchParams()
    Array.from(new Set(imageIds.filter((id) => Number.isFinite(id) && id > 0)))
      .slice(0, 100)
      .forEach((id) => query.append('imageIds', String(id)))
    return request<Record<string, ImageInteractionStatus>>(`/interactions/images/status?${query.toString()}`)
  },

  interactionStatus(imageId: number) {
    return request<ImageInteractionStatus>(`/interactions/images/${imageId}/status`)
  },
  follow(userId: number, scene = 'detail') {
    return request<void>(`/social/follow/${userId}?scene=${encodeURIComponent(scene)}`, { method: 'POST' })
  },
  unfollow(userId: number) {
    return request<void>(`/social/follow/${userId}`, { method: 'DELETE' })
  },
  followStatus(userId: number) {
    return request<FollowStatus>(`/social/follow-status/${userId}`)
  },
  profile(userId: number) {
    return request<UserSummary>(`/users/${userId}`)
  },
  updateProfile(payload: { nickname: string; avatarUrl?: string; backgroundUrl?: string; bio?: string }) {
    return request<ProfileReviewView>('/users/me', { method: 'PUT', body: JSON.stringify(payload) })
  },
  profileReview() {
    return request<ProfileReviewView | null>('/users/me/profile-review')
  },
  notifications(limit = 20) {
    return request<NotificationView[]>(`/users/me/notifications?limit=${limit}`)
  },
  userStats(userId: number) {
    return request<UserStats>(`/users/${userId}/stats`)
  },
  userImages(userId: number, limit = 30) {
    return request<ImageView[]>(`/users/${userId}/images?limit=${limit}`)
  },
  userLikedImages(userId: number, limit = 12) {
    return request<ImageView[]>(`/users/${userId}/liked-images?limit=${limit}`)
  },
  userFavoriteImages(userId: number, limit = 30) {
    return request<ImageView[]>(`/users/${userId}/favorite-images?limit=${limit}`)
  },
  userFollowing(userId: number, limit = 50) {
    return request<UserSummary[]>(`/users/${userId}/following?limit=${limit}`)
  },
  userFollowers(userId: number, limit = 50) {
    return request<UserSummary[]>(`/users/${userId}/followers?limit=${limit}`)
  },
  search(keyword: string) {
    return request<SearchResult>(`/search?keyword=${encodeURIComponent(keyword)}`)
  },
  searchSuggestions(keyword = '') {
    return request<SearchSuggestionResponse>(`/search/suggestions?keyword=${encodeURIComponent(keyword)}`)
  },
  trendingTopics(limit = 20) {
    return request<TopicView[]>(`/topics/trending?limit=${limit}`)
  },
  categoryTree() {
    return request<CategoryView[]>('/metadata/categories/tree')
  },
  imageTags(type?: string, limit = 100) {
    const query = new URLSearchParams({ limit: String(limit) })
    if (type) query.set('type', type)
    return request<TagView[]>(`/metadata/tags?${query.toString()}`)
  },
}
