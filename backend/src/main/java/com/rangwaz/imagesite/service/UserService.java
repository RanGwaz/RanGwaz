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
     * @return updated summary
     */
    ApiDtos.UserSummary updateProfile(Long userId, ApiDtos.UpdateProfileRequest request);

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
