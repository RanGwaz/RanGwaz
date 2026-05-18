package com.rangwaz.imagesite.service.impl;

import com.rangwaz.imagesite.common.api.PageResponse;
import com.rangwaz.imagesite.dto.ApiDtos;
import com.rangwaz.imagesite.mapper.PostMapper;
import com.rangwaz.imagesite.service.FeedService;
import org.springframework.stereotype.Service;

/**
 * Default feed service using a hot-score baseline ready for future ranking replacement.
 */
@Service
public class FeedServiceImpl implements FeedService {
    private final PostMapper postMapper;
    private final PostServiceImpl postService;

    /**
     * Creates the feed service.
     *
     * @param postMapper post mapper
     * @param postService post service
     */
    public FeedServiceImpl(PostMapper postMapper, PostServiceImpl postService) {
        this.postMapper = postMapper;
        this.postService = postService;
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
    public PageResponse<ApiDtos.PostView> home(Long userId, int page, int size) {
        int safePage = Math.max(1, page);
        int safeSize = Math.max(1, Math.min(size, 60));
        int offset = (safePage - 1) * safeSize;
        var records = postMapper.selectFeed(offset, safeSize).stream()
                .map(post -> postService.toView(post, "热门图片与新鲜内容混排"))
                .toList();
        return new PageResponse<>(records, postMapper.countPublished(), safePage, safeSize);
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
    public PageResponse<ApiDtos.PostView> similar(Long postId, int page, int size) {
        postService.requirePost(postId);
        int safePage = Math.max(1, page);
        int safeSize = Math.max(1, Math.min(size, 60));
        int offset = (safePage - 1) * safeSize;
        var records = postMapper.selectSimilar(postId, offset, safeSize).stream()
                .map(post -> postService.toView(post, "与你正在看的内容相似"))
                .toList();
        return new PageResponse<>(records, postMapper.countSimilar(postId), safePage, safeSize);
    }
}
