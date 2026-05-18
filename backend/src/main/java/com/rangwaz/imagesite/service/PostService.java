package com.rangwaz.imagesite.service;

import com.rangwaz.imagesite.dto.ApiDtos;

import java.util.List;

/**
 * Service interface for post creation, detail, and related reads.
 */
public interface PostService {
    /**
     * Creates a post.
     *
     * @param authorId author id
     * @param request creation request
     * @return created post view
     */
    ApiDtos.PostView create(Long authorId, ApiDtos.CreatePostRequest request);

    /**
     * Gets a post detail.
     *
     * @param postId post id
     * @param viewerId optional viewer id
     * @return post view
     */
    ApiDtos.PostView detail(Long postId, Long viewerId);

    /**
     * Lists posts authored by a user.
     *
     * @param userId author id
     * @param limit maximum rows
     * @return post views
     */
    List<ApiDtos.PostView> byUser(Long userId, int limit);

    /**
     * Tracks a post click.
     *
     * @param postId post id
     * @param viewerId optional viewer id
     * @param scene scene
     * @param position position
     */
    void click(Long postId, Long viewerId, String scene, Integer position);

    /**
     * Tracks a share.
     *
     * @param postId post id
     */
    void share(Long postId);
}
