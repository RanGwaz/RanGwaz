/** HTTP client and typed API helpers for the React frontend. */
import type {
  ApiResponse,
  AuthTokenResponse,
  CommentView,
  FollowStatus,
  PageResponse,
  PostInteractionStatus,
  PostView,
  SearchResult,
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
  const payload = (await response.json()) as ApiResponse<T>
  if (!response.ok || !payload.success) throw new Error(payload.message || '请求失败')
  return payload.data
}

export const api = {
  register(payload: { username: string; password: string; nickname: string }) {
    return request<AuthTokenResponse>('/api/auth/register', { method: 'POST', body: JSON.stringify(payload) })
  },
  login(payload: { username: string; password: string }) {
    return request<AuthTokenResponse>('/api/auth/login', { method: 'POST', body: JSON.stringify(payload) })
  },
  me() {
    return request<AuthTokenResponse>('/api/auth/me')
  },
  homeFeed(page = 1, pageSize = 30) {
    return request<PageResponse<PostView>>(`/api/feed?page=${page}&pageSize=${pageSize}`)
  },
  similarPosts(postId: number, page = 1, size = 24) {
    return request<PageResponse<PostView>>(`/api/feed/posts/${postId}/similar?page=${page}&size=${size}`)
  },
  postDetail(postId: number) {
    return request<PostView>(`/api/posts/${postId}`)
  },
  trackPostClick(postId: number, scene = 'feed', position?: number) {
    const query = new URLSearchParams({ scene })
    if (position) query.set('position', String(position))
    return request<void>(`/api/posts/${postId}/click?${query.toString()}`, { method: 'POST' })
  },
  trackPostShare(postId: number) {
    return request<void>(`/api/posts/${postId}/share`, { method: 'POST' })
  },
  createPost(payload: unknown) {
    return request<PostView>('/api/posts', { method: 'POST', body: JSON.stringify(payload) })
  },
  uploadImage(file: File) {
    const form = new FormData()
    form.append('file', file)
    return request<UploadResponse>('/api/media/upload', { method: 'POST', body: form })
  },
  toggleLike(postId: number) {
    return request<ToggleResult>(`/api/interactions/posts/${postId}/like/toggle`, { method: 'POST' })
  },
  toggleFavorite(postId: number) {
    return request<ToggleResult>(`/api/interactions/posts/${postId}/favorite/toggle`, { method: 'POST' })
  },
  commentsPage(postId: number, page = 1, size = 20) {
    return request<PageResponse<CommentView>>(`/api/interactions/posts/${postId}/comments/page?page=${page}&size=${size}`)
  },
  comment(postId: number, content: string, parentCommentId?: number) {
    return request<CommentView>(`/api/interactions/posts/${postId}/comments`, { method: 'POST', body: JSON.stringify({ content, parentCommentId }) })
  },
  interactionStatus(postId: number) {
    return request<PostInteractionStatus>(`/api/interactions/posts/${postId}/status`)
  },
  follow(userId: number, scene = 'detail') {
    return request<void>(`/api/social/follow/${userId}?scene=${encodeURIComponent(scene)}`, { method: 'POST' })
  },
  unfollow(userId: number) {
    return request<void>(`/api/social/follow/${userId}`, { method: 'DELETE' })
  },
  followStatus(userId: number) {
    return request<FollowStatus>(`/api/social/follow-status/${userId}`)
  },
  profile(userId: number) {
    return request<UserSummary>(`/api/users/${userId}`)
  },
  userStats(userId: number) {
    return request<UserStats>(`/api/users/${userId}/stats`)
  },
  userPosts(userId: number, limit = 30) {
    return request<PostView[]>(`/api/users/${userId}/posts?limit=${limit}`)
  },
  search(keyword: string) {
    return request<SearchResult>(`/api/search?keyword=${encodeURIComponent(keyword)}`)
  },
  trendingTopics(limit = 20) {
    return request<TopicView[]>(`/api/topics/trending?limit=${limit}`)
  },
}
