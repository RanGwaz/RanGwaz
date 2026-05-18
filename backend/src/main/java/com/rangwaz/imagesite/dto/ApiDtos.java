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
     * Media upload response.
     */
    public record UploadResponse(String objectKey, String fileUrl, String fileType, String thumbUrl, Integer width, Integer height) {
    }

    /**
     * Asset request used when creating a post.
     */
    public record PostAssetRequest(String objectKey, String fileUrl, String fileType, String thumbUrl, Integer width, Integer height, Integer sortOrder) {
    }

    /**
     * Asset view used by feeds and detail pages.
     */
    public record PostAssetView(Long id, String objectKey, String fileUrl, String fileType, String thumbUrl, Integer width, Integer height, Integer sortOrder) {
    }

    /**
     * Image compatibility view for old frontend consumers.
     */
    public record PostImageView(String url, Integer width, Integer height) {
    }

    /**
     * Post creation request.
     */
    public record CreatePostRequest(@NotBlank @Size(max = 160) String title,
                                    @Size(max = 5000) String content,
                                    String postType,
                                    List<String> imageUrls,
                                    List<String> tags,
                                    List<String> topics,
                                    @Valid List<PostAssetRequest> assets) {
    }

    /**
     * Post view shared by feed, search, and detail pages.
     */
    public record PostView(Long id,
                           UserSummary author,
                           String title,
                           String content,
                           List<String> tags,
                           String channel,
                           String channelCode,
                           String postType,
                           List<PostAssetView> assets,
                           List<PostImageView> images,
                           String coverUrl,
                           String thumbUrl,
                           Integer likeCount,
                           Integer favoriteCount,
                           Integer collectCount,
                           Integer commentCount,
                           Integer shareCount,
                           Integer viewCount,
                           String recommendationReason,
                           LocalDateTime createdAt) {
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
     * Search response containing users, posts, and topics.
     */
    public record SearchResult(List<UserSummary> users, List<PostView> posts, List<TopicView> topics) {
    }

    /**
     * Active/inactive toggle response.
     */
    public record ToggleResult(boolean active) {
    }

    /**
     * Interaction status response for a post and current user.
     */
    public record PostInteractionStatus(boolean liked, boolean favorited) {
    }

    /**
     * Follow status response for a target user.
     */
    public record FollowStatus(boolean following) {
    }

    /**
     * User statistics response.
     */
    public record UserStats(long postCount, long followingCount, long followerCount) {
    }

    /**
     * Behavior tracking request for recommendation data collection.
     */
    public record BehaviorRequest(Long postId, String behaviorType, String scene, Integer position, Integer duration) {
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
}
