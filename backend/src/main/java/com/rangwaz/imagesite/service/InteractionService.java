package com.rangwaz.imagesite.service;

import com.rangwaz.imagesite.common.api.PageResponse;
import com.rangwaz.imagesite.dto.ApiDtos;

/**
 * Service interface for likes, favorites, comments, follows, and behavior events.
 */
public interface InteractionService {
    /**
     * Toggles a like.
     *
     * @param userId user id
     * @param postId post id
     * @return toggle result
     */
    ApiDtos.ToggleResult toggleLike(Long userId, Long postId);

    /**
     * Toggles a favorite.
     *
     * @param userId user id
     * @param postId post id
     * @return toggle result
     */
    ApiDtos.ToggleResult toggleFavorite(Long userId, Long postId);

    /**
     * Gets current user's interaction status.
     *
     * @param userId user id
     * @param postId post id
     * @return status response
     */
    ApiDtos.PostInteractionStatus status(Long userId, Long postId);

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
     * @param request behavior request
     */
    void behavior(Long userId, ApiDtos.BehaviorRequest request);
}
