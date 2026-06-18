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
     * @param feedSessionId stable frontend feed session id
     * @param refreshSeed seed used to keep one refresh's pagination stable
     * @return page response
     */
    PageResponse<ApiDtos.ImageView> home(Long userId, int page, int size, String feedSessionId, String refreshSeed);

    /**
     * Loads posts similar to a detail post.
     *
     * @param postId post id
     * @param page page number
     * @param size page size
     * @return page response
     */
    PageResponse<ApiDtos.ImageView> similar(Long postId, int page, int size);
}
