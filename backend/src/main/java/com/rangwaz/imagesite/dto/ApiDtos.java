package com.rangwaz.imagesite.dto;

import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;

import java.time.LocalDateTime;
import java.util.List;

/**
 * Request and response DTOs used by the image-site API.
 */
public final class ApiDtos {
    private ApiDtos() {
    }

    /**
     * Compact user summary sent to the frontend.
     */
    public record UserSummary(Long id, String username, String nickname, String avatarUrl, String backgroundUrl, String bio) {
    }

    /**
     * Client network address response.
     */
    public record ClientIpResponse(String ip) {
    }

    /**
     * Login or register token payload.
     */
    public record AuthTokenResponse(String accessToken, String tokenType, long expiresInSeconds, UserSummary me) {
    }

    /**
     * Username-password login request.
     */
    public record LoginRequest(@NotBlank String username, @NotBlank String password) {
    }

    /**
     * Username-password register request.
     */
    public record RegisterRequest(@NotBlank String username, @NotBlank String password, @NotBlank String nickname) {
    }

    /**
     * Sends an SMS verification code for phone sign-in.
     */
    public record SendSmsCodeRequest(@NotBlank String phone, String scene) {
    }

    /**
     * SMS code request result. mockCode is only present in local mock mode.
     */
    public record SmsCodeResponse(boolean sent, String mockCode, long expiresInSeconds, long cooldownSeconds, boolean registered) {
    }

    /**
     * Phone verification-code login request.
     */
    public record PhoneLoginRequest(@NotBlank String phone, @NotBlank String code, String password, String passwordConfirm) {
    }

    /**
     * Phone-password login request.
     */
    public record PhonePasswordLoginRequest(@NotBlank String phone, @NotBlank String password) {
    }

    /**
     * Replaces an existing phone account password after SMS verification.
     */
    public record PhonePasswordResetRequest(@NotBlank String phone,
                                            @NotBlank String code,
                                            @NotBlank String password,
                                            @NotBlank String passwordConfirm) {
    }

    /**
     * Media upload response.
     */
    public record UploadResponse(String objectKey,
                                 String fileUrl,
                                 String fileType,
                                 String thumbUrl,
                                 Integer width,
                                 Integer height,
                                 Long fileSize,
                                 String hash) {
    }

    /**
     * Asset request used when creating a post.
     */
    public record ImageAssetRequest(String objectKey,
                                   String fileUrl,
                                   String fileType,
                                   String thumbUrl,
                                   Integer width,
                                   Integer height,
                                   Long fileSize,
                                   String hash,
                                   Integer sortOrder) {
    }

    /**
     * Asset view used by feeds and detail pages.
     */
    public record ImageAssetView(Long id,
                                String objectKey,
                                String fileUrl,
                                String fileType,
                                String thumbUrl,
                                Integer width,
                                Integer height,
                                Long fileSize,
                                String hash,
                                Integer sortOrder,
                                ImageMetadataView metadata) {
    }

    /**
     * Image compatibility view for old frontend consumers.
     */
    public record ImageSourceView(String url, Integer width, Integer height) {
    }

    /**
     * Post creation request.
     */
    public record CreateImageRequest(@Size(max = 160) String title,
                                    @Size(max = 5000) String content,
                                    String postType,
                                    List<String> imageUrls,
                                    List<String> tags,
                                    List<String> topics,
                                    @Valid List<ImageAssetRequest> assets) {
    }

    /**
     * Hierarchical image category view.
     */
    public record CategoryView(Long id, String name, Long parentId, String slug, Integer sortNo, List<CategoryView> children) {
    }

    /**
     * Typed image tag view.
     */
    public record TagView(Long id, String name, String type, String slug) {
    }

    /**
     * Image tag assignment view with confidence and source.
     */
    public record ImageTagView(Long id, String name, String type, String slug, Double confidence, String source) {
    }

    /**
     * Image metadata view used by assets and future vector workers.
     */
    public record ImageMetadataView(Long id,
                                    Long imageId,
                                    CategoryView mainCategory,
                                    String ratio,
                                    Long fileSize,
                                    String hash,
                                    List<ImageTagView> tags) {
    }

    /**
     * Post view shared by feed, search, and detail pages.
     */
    public record ImageView(Long id,
                           UserSummary author,
                           String title,
                           String content,
                           List<String> tags,
                           String channel,
                           String channelCode,
                           String postType,
                           List<ImageAssetView> assets,
                           List<ImageSourceView> images,
                           String coverUrl,
                           String thumbUrl,
                           Integer likeCount,
                           Integer favoriteCount,
                           Integer collectCount,
                           Integer commentCount,
                           Integer shareCount,
                           Integer viewCount,
                           String recommendationReason,
                           LocalDateTime createdAt,
                           String status,
                           String reviewReason) {
    }

    /**
     * Topic view used by search and publish suggestions.
     */
    public record TopicView(Long id, String name, String slug, String description, String coverUrl, Integer postCount, Integer followerCount, Double hotScore) {
    }

    /**
     * Comment view used by post detail pages.
     */
    public record CommentView(Long id, UserSummary author, Long parentCommentId, UserSummary replyToUser, String content, LocalDateTime createdAt) {
    }

    /**
     * Search response containing users, images, and topics.
     */
    public record SearchResult(List<UserSummary> users,
                               List<ImageView> images,
                               List<TopicView> topics,
                               List<SearchSuggestionItem> related) {
    }

    /**
     * One clickable search idea for the focused search panel.
     */
    public record SearchSuggestionItem(String keyword, String kind, String imageUrl, Long postCount) {
    }

    /**
     * Search ideas grouped by product intent.
     */
    public record SearchSuggestionResponse(List<SearchSuggestionItem> recommended, List<SearchSuggestionItem> trending) {
    }

    /**
     * Active/inactive toggle response.
     */
    public record ToggleResult(boolean active) {
    }

    /**
     * Interaction status response for a post and current user.
     */
    public record ImageInteractionStatus(boolean liked, boolean favorited) {
    }

    /**
     * Follow status response for a target user.
     */
    public record FollowStatus(boolean following) {
    }

    /**
     * User statistics response.
     */
    public record UserStats(long imageCount, long followingCount, long followerCount, long likedCount, long favoriteCount) {
    }

    /**
     * Behavior tracking request for image analytics.
     */
    public record BehaviorRequest(Long imageId,
                                  String behaviorType,
                                  String scene,
                                  Integer position,
                                  Integer duration,
                                  String visitorId,
                                  Double latitude,
                                  Double longitude,
                                  String locationLabel,
                                  String decisionId,
                                  String eventId,
                                  String source,
                                  Double score,
                                  LocalDateTime occurredAt) {
    }

    /**
     * Batch behavior tracking request for feed impressions.
     */
    public record BehaviorBatchRequest(String visitorId, List<BehaviorRequest> events) {
    }

    /**
     * Comment creation request.
     */
    public record CreateCommentRequest(@NotBlank @Size(max = 1000) String content, Long parentCommentId) {
    }

    /**
     * Profile update request.
     */
    public record UpdateProfileRequest(String nickname, String avatarUrl, String backgroundUrl, String bio) {
    }

    /**
     * Profile update review view.
     */
    public record ProfileReviewView(Long id,
                                    Long userId,
                                    String nickname,
                                    String avatarUrl,
                                    String backgroundUrl,
                                    String bio,
                                    String status,
                                    String reviewReason,
                                    LocalDateTime reviewedAt,
                                    LocalDateTime createdAt) {
    }

    /**
     * Moderation decision request for admin/manual review.
     */
    public record ReviewDecisionRequest(@NotBlank String status, String reason) {
    }

    /**
     * User notification view.
     */
    public record NotificationView(Long id,
                                   String type,
                                   String title,
                                   String content,
                                   String targetType,
                                   Long targetId,
                                   Boolean read,
                                   LocalDateTime createdAt) {
    }
}
