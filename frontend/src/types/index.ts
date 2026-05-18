/** Shared frontend API types for the image website. */
export interface ApiResponse<T> {
  success: boolean
  code: string
  data: T
  message: string
  timestamp: string
}

export interface UserSummary {
  id: number
  username: string
  nickname: string
  avatarUrl?: string
  backgroundUrl?: string
  bio?: string
}

export interface AuthTokenResponse {
  accessToken: string
  tokenType: string
  expiresInSeconds: number
  me: UserSummary
}

export interface PostAssetView {
  id: number
  objectKey: string
  fileUrl: string
  fileType: string
  thumbUrl?: string
  width?: number
  height?: number
  sortOrder: number
}

export interface PostImageView {
  url: string
  width?: number
  height?: number
}

export interface PostView {
  id: number
  author: UserSummary
  title: string
  content?: string
  tags: string[]
  channel?: string
  channelCode?: string
  postType?: string
  assets: PostAssetView[]
  images?: PostImageView[]
  coverUrl?: string
  thumbUrl?: string
  likeCount: number
  favoriteCount: number
  collectCount?: number
  commentCount: number
  shareCount?: number
  viewCount: number
  recommendationReason?: string
  createdAt: string
}

export interface CommentView {
  id: number
  author: UserSummary
  parentCommentId?: number
  replyToUser?: UserSummary
  content: string
  createdAt: string
}

export interface PageResponse<T> {
  records: T[]
  total: number
  page: number
  size: number
}

export interface TopicView {
  id: number
  name: string
  slug: string
  description?: string
  coverUrl?: string
  postCount?: number
  followerCount?: number
  hotScore?: number
}

export interface SearchResult {
  users: UserSummary[]
  posts: PostView[]
  topics: TopicView[]
}

export interface UploadResponse {
  objectKey: string
  fileUrl: string
  fileType: string
  thumbUrl?: string
  width?: number
  height?: number
}

export interface ToggleResult {
  active: boolean
}

export interface PostInteractionStatus {
  liked: boolean
  favorited: boolean
}

export interface FollowStatus {
  following: boolean
}

export interface UserStats {
  postCount: number
  followingCount: number
  followerCount: number
}
