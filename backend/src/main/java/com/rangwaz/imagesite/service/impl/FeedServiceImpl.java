package com.rangwaz.imagesite.service.impl;

import com.rangwaz.imagesite.common.api.PageResponse;
import com.rangwaz.imagesite.dto.ApiDtos;
import com.rangwaz.imagesite.mapper.ImageContentMapper;
import com.rangwaz.imagesite.service.FeedService;
import org.springframework.stereotype.Service;

/**
 * Default feed service using a hot-score baseline ready for future ranking replacement.
 */
@Service
public class FeedServiceImpl implements FeedService {
    private final ImageContentMapper imageContentMapper;
    private final ImageServiceImpl imageService;

    /**
     * Creates the feed service.
     *
     * @param imageContentMapper image content mapper
     * @param imageService post service
     */
    public FeedServiceImpl(ImageContentMapper imageContentMapper, ImageServiceImpl imageService) {
        this.imageContentMapper = imageContentMapper;
        this.imageService = imageService;
    }

    /**
     * Loads the home feed.
     *
     * @param userId optional user id
     * @param page page number
     * @param size page size
     * @return page response
     */
    @Override
    public PageResponse<ApiDtos.ImageView> home(Long userId, int page, int size) {
        int safePage = Math.max(1, page);
        int safeSize = Math.max(1, Math.min(size, 60));
        int offset = (safePage - 1) * safeSize;
        var records = imageService.toViews(imageContentMapper.selectFeed(offset, safeSize), "home");
        return new PageResponse<>(records, imageContentMapper.countPublished(), safePage, safeSize);
    }

    /**
     * Loads posts similar to a detail post.
     *
     * @param postId post id
     * @param page page number
     * @param size page size
     * @return page response
     */
    @Override
    public PageResponse<ApiDtos.ImageView> similar(Long postId, int page, int size) {
        imageService.requirePost(postId);
        int safePage = Math.max(1, page);
        int safeSize = Math.max(1, Math.min(size, 60));
        int offset = (safePage - 1) * safeSize;
        var records = imageService.toViews(imageContentMapper.selectSimilar(postId, offset, safeSize), "similar");
        return new PageResponse<>(records, imageContentMapper.countSimilar(postId), safePage, safeSize);
    }
}
