package com.rangwaz.imagesite.service;

import com.rangwaz.imagesite.dto.ApiDtos;

import java.util.List;

/**
 * Service interface for user profile reads and writes.
 */
public interface UserService {
    /**
     * Finds a user summary.
     *
     * @param userId user id
     * @return user summary
     */
    ApiDtos.UserSummary findSummary(Long userId);

    /**
     * Updates the current user's profile.
     *
     * @param userId current user id
     * @param request update request
     * @return created review request
     */
    ApiDtos.ProfileReviewView updateProfile(Long userId, ApiDtos.UpdateProfileRequest request);

    /**
     * Gets current user's latest profile review request.
     *
     * @param userId user id
     * @return latest review
     */
    ApiDtos.ProfileReviewView latestProfileReview(Long userId);

    /**
     * Lists profile update requests in a moderation queue.
     *
     * @param status review status
     * @param limit maximum rows
     * @return review views
     */
    List<ApiDtos.ProfileReviewView> profileReviewQueue(String status, int limit);

    /**
     * Applies a manual profile review decision.
     *
     * @param reviewId review id
     * @param request decision request
     * @return review view
     */
    ApiDtos.ProfileReviewView decideProfileReview(Long reviewId, ApiDtos.ReviewDecisionRequest request);

    /**
     * Lists recent user notifications.
     *
     * @param userId user id
     * @param limit maximum rows
     * @return notifications
     */
    List<ApiDtos.NotificationView> notifications(Long userId, int limit);

    /**
     * Gets user statistics.
     *
     * @param userId user id
     * @return user stats
     */
    ApiDtos.UserStats stats(Long userId);

    /**
     * Searches users.
     *
     * @param keyword keyword
     * @param limit maximum rows
     * @return matching users
     */
    List<ApiDtos.UserSummary> search(String keyword, int limit);
}
