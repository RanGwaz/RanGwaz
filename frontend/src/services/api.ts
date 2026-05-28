/** HTTP client and typed API helpers for the React frontend. */
import type {
  ApiResponse,
  AuthTokenResponse,
  CategoryView,
  CommentView,
  FollowStatus,
  PageResponse,
  ImageInteractionStatus,
  ImageView,
  SearchResult,
  TagView,
  ToggleResult,
  TopicView,
  UploadResponse,
  UserStats,
  UserSummary,
} from '../types'

const TOKEN_KEY = 'rangwaz-token'

export function getToken() {
  return localStorage.getItem(TOKEN_KEY) || ''
}

export function setToken(token: string) {
  if (token) localStorage.setItem(TOKEN_KEY, token)
  else localStorage.removeItem(TOKEN_KEY)
}

async function request<T>(path: string, init: RequestInit = {}) {
  const headers = new Headers(init.headers)
  const token = getToken()
  if (token) headers.set('Authorization', `Bearer ${token}`)
  if (!(init.body instanceof FormData) && init.body !== undefined) headers.set('Content-Type', 'application/json')
  const response = await fetch(path, { ...init, headers })
  const text = await response.text()
  let payload: ApiResponse<T>
  try {
    payload = text ? JSON.parse(text) as ApiResponse<T> : {
      code: response.ok ? 'OK' : 'EMPTY_RESPONSE',
      data: undefined as T,
      message: '',
      success: response.ok,
      timestamp: new Date().toISOString(),
    }
  } catch {
    throw new Error(`接口 ${path} 返回了非 JSON 内容，请检查前端代理或后端路由`)
  }
  if (!response.ok || !payload.success) throw new Error(payload.message || '请求失败')
  return payload.data
}

export const api = {
  register(payload: { username: string; password: string; nickname: string }) {
    return request<AuthTokenResponse>('/auth/register', { method: 'POST', body: JSON.stringify(payload) })
  },
  login(payload: { username: string; password: string }) {
    return request<AuthTokenResponse>('/auth/login', { method: 'POST', body: JSON.stringify(payload) })
  },
  logout() {
    return request<void>('/auth/logout', { method: 'POST' })
  },
  me() {
    return request<AuthTokenResponse>('/auth/me')
  },
  homeFeed(page = 1, pageSize = 30) {
    return request<PageResponse<ImageView>>(`/feed?page=${page}&pageSize=${pageSize}`)
  },
  similarImages(imageId: number, page = 1, size = 24) {
    return request<PageResponse<ImageView>>(`/feed/images/${imageId}/similar?page=${page}&size=${size}`)
  },
  imageDetail(imageId: number) {
    return request<ImageView>(`/images/${imageId}`)
  },
  trackImageClick(imageId: number, scene = 'feed', position?: number) {
    const query = new URLSearchParams({ scene })
    if (position) query.set('position', String(position))
    return request<void>(`/images/${imageId}/click?${query.toString()}`, { method: 'POST' })
  },
  trackImageShare(imageId: number) {
    return request<void>(`/images/${imageId}/share`, { method: 'POST' })
  },
  createImage(payload: unknown) {
    return request<ImageView>('/images', { method: 'POST', body: JSON.stringify(payload) })
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
    return request<UserSummary>('/users/me', { method: 'PUT', body: JSON.stringify(payload) })
  },
  userStats(userId: number) {
    return request<UserStats>(`/users/${userId}/stats`)
  },
  userImages(userId: number, limit = 30) {
    return request<ImageView[]>(`/users/${userId}/images?limit=${limit}`)
  },
  search(keyword: string) {
    return request<SearchResult>(`/search?keyword=${encodeURIComponent(keyword)}`)
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
