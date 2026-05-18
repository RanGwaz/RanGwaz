package com.rangwaz.imagesite.service.impl;

import com.rangwaz.imagesite.dto.ApiDtos;
import com.rangwaz.imagesite.mapper.PostMapper;
import com.rangwaz.imagesite.service.SearchService;
import com.rangwaz.imagesite.service.TopicService;
import com.rangwaz.imagesite.service.UserService;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

import java.util.List;

/**
 * Default global search service implementation.
 */
@Service
public class SearchServiceImpl implements SearchService {
    private final PostMapper postMapper;
    private final PostServiceImpl postService;
    private final UserService userService;
    private final TopicService topicService;

    /**
     * Creates the search service.
     *
     * @param postMapper post mapper
     * @param postService post service
     * @param userService user service
     * @param topicService topic service
     */
    public SearchServiceImpl(PostMapper postMapper, PostServiceImpl postService, UserService userService, TopicService topicService) {
        this.postMapper = postMapper;
        this.postService = postService;
        this.userService = userService;
        this.topicService = topicService;
    }

    /**
     * Searches posts, users, and topics.
     *
     * @param keyword keyword
     * @return search result
     */
    @Override
    public ApiDtos.SearchResult search(String keyword) {
        String trimmed = keyword == null ? "" : keyword.trim();
        if (!StringUtils.hasText(trimmed)) {
            return new ApiDtos.SearchResult(List.of(), List.of(), topicService.trending(12));
        }
        var posts = postMapper.search(trimmed, 36).stream()
                .map(post -> postService.toView(post, "搜索关键词匹配"))
                .toList();
        return new ApiDtos.SearchResult(userService.search(trimmed, 12), posts, topicService.search(trimmed, 12));
    }
}
