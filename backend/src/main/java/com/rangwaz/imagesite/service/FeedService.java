package com.rangwaz.imagesite.service;

import com.rangwaz.imagesite.common.api.PageResponse;
import com.rangwaz.imagesite.dto.ApiDtos;

/**
 * Service interface for home and similar feeds.
 */
public interface FeedService {
    /**
     * Loads the home feed.
     *
     * @param userId optional user id
     * @param page page number
     * @param size page size
     * @return page response
     */
    PageResponse<ApiDtos.PostView> home(Long userId, int page, int size);

    /**
     * Loads posts similar to a detail post.
     *
     * @param postId post id
     * @param page page number
     * @param size page size
     * @return page response
     */
    PageResponse<ApiDtos.PostView> similar(Long postId, int page, int size);
}
