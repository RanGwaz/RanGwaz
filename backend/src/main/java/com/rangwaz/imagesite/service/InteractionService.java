package com.rangwaz.imagesite.service;

import com.rangwaz.imagesite.common.api.PageResponse;
import com.rangwaz.imagesite.dto.ApiDtos;

import java.util.List;

/**
 * Service interface for likes, favorites, comments, follows, and behavior events.
 */
public interface InteractionService {
    /**
     * Toggles a like.
     *
     * @param userId user id
     * @param postId post id
     * @param latitude optional latitude
     * @param longitude optional longitude
     * @param locationLabel optional human-readable location
     * @return toggle result
     */
    ApiDtos.ToggleResult toggleLike(Long userId, Long postId, Double latitude, Double longitude, String locationLabel);

    /**
     * Toggles a favorite.
     *
     * @param userId user id
     * @param postId post id
     * @param latitude optional latitude
     * @param longitude optional longitude
     * @param locationLabel optional human-readable location
     * @return toggle result
     */
    ApiDtos.ToggleResult toggleFavorite(Long userId, Long postId, Double latitude, Double longitude, String locationLabel);

    /**
     * Gets current user's interaction status.
     *
     * @param userId user id
     * @param postId post id
     * @return status response
     */
    ApiDtos.ImageInteractionStatus status(Long userId, Long postId);

    /**
     * Lists images liked by a user.
     *
     * @param userId user id
     * @param limit maximum rows
     * @return liked images
     */
    List<ApiDtos.ImageView> likedImages(Long userId, int limit);

    /**
     * Lists images favorited by a user.
     *
     * @param userId user id
     * @param limit maximum rows
     * @return favorite images
     */
    List<ApiDtos.ImageView> favoriteImages(Long userId, int limit);

    /**
     * Lists users followed by a user.
     *
     * @param userId user id
     * @param limit maximum rows
     * @return followed users
     */
    List<ApiDtos.UserSummary> following(Long userId, int limit);

    /**
     * Lists users following a user.
     *
     * @param userId user id
     * @param limit maximum rows
     * @return follower users
     */
    List<ApiDtos.UserSummary> followers(Long userId, int limit);

    /**
     * Pages comments.
     *
     * @param postId post id
     * @param page page number
     * @param size page size
     * @return comment page
     */
    PageResponse<ApiDtos.CommentView> comments(Long postId, int page, int size);

    /**
     * Creates a comment.
     *
     * @param userId author id
     * @param postId post id
     * @param request creation request
     * @return created comment
     */
    ApiDtos.CommentView comment(Long userId, Long postId, ApiDtos.CreateCommentRequest request);

    /**
     * Follows a user.
     *
     * @param followerId follower id
     * @param followeeId followee id
     * @param scene scene
     */
    void follow(Long followerId, Long followeeId, String scene);

    /**
     * Unfollows a user.
     *
     * @param followerId follower id
     * @param followeeId followee id
     */
    void unfollow(Long followerId, Long followeeId);

    /**
     * Gets follow status.
     *
     * @param followerId follower id
     * @param followeeId followee id
     * @return status response
     */
    ApiDtos.FollowStatus followStatus(Long followerId, Long followeeId);

    /**
     * Tracks a behavior event.
     *
     * @param userId optional user id
     * @param visitorId optional visitor id
     * @param request behavior request
     */
    void behavior(Long userId, String visitorId, ApiDtos.BehaviorRequest request);

    /**
     * Tracks multiple behavior events.
     *
     * @param userId optional user id
     * @param visitorId optional visitor id
     * @param request batch behavior request
     */
    void behaviors(Long userId, String visitorId, ApiDtos.BehaviorBatchRequest request);
}
