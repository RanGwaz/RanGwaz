package com.rangwaz.imagesite.service;

import com.rangwaz.imagesite.dto.ApiDtos;

import java.util.List;

/**
 * Service interface for post creation, detail, and related reads.
 */
public interface ImageService {
    /**
     * Creates a post.
     *
     * @param authorId author id
     * @param request creation request
     * @return created post view
     */
    ApiDtos.ImageView create(Long authorId, ApiDtos.CreateImageRequest request);

    /**
     * Gets a post detail.
     *
     * @param postId post id
     * @param viewerId optional viewer id
     * @return post view
     */
    ApiDtos.ImageView detail(Long postId, Long viewerId);

    /**
     * Lists posts authored by a user.
     *
     * @param userId author id
     * @param limit maximum rows
     * @return post views
     */
    List<ApiDtos.ImageView> byUser(Long userId, int limit);

    /**
     * Lists posts authored by a user, optionally including review-only rows for owner.
     *
     * @param userId author id
     * @param limit maximum rows
     * @param includeReviewRows whether pending/rejected rows should be included
     * @return post views
     */
    List<ApiDtos.ImageView> byUser(Long userId, int limit, boolean includeReviewRows);

    /**
     * Lists posts in a moderation queue.
     *
     * @param status review status
     * @param limit maximum rows
     * @return post views
     */
    List<ApiDtos.ImageView> reviewQueue(String status, int limit);

    /**
     * Applies a manual image review decision.
     *
     * @param imageId image id
     * @param request decision request
     * @return image view
     */
    ApiDtos.ImageView decideImageReview(Long imageId, ApiDtos.ReviewDecisionRequest request);

    /**
     * Tracks a post click.
     *
     * @param postId post id
     * @param viewerId optional viewer id
     * @param visitorId optional visitor id
     * @param scene scene
     * @param position position
     * @param latitude optional latitude
     * @param longitude optional longitude
     * @param locationLabel optional human-readable location
     */
    void click(Long postId, Long viewerId, String visitorId, String scene, Integer position, Double latitude, Double longitude, String locationLabel);

    /**
     * Tracks a share.
     *
     * @param postId post id
     */
    void share(Long postId);
}
