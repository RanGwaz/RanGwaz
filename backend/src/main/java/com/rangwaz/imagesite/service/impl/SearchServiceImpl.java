package com.rangwaz.imagesite.service.impl;

import com.rangwaz.imagesite.dto.ApiDtos;
import com.rangwaz.imagesite.mapper.ImageContentMapper;
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
    private final ImageContentMapper imageContentMapper;
    private final ImageServiceImpl imageService;
    private final UserService userService;
    private final TopicService topicService;

    /**
     * Creates the search service.
     *
     * @param imageContentMapper image content mapper
     * @param imageService post service
     * @param userService user service
     * @param topicService topic service
     */
    public SearchServiceImpl(ImageContentMapper imageContentMapper, ImageServiceImpl imageService, UserService userService, TopicService topicService) {
        this.imageContentMapper = imageContentMapper;
        this.imageService = imageService;
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
        var posts = imageService.toViews(imageContentMapper.search(trimmed, 36), "search");
        return new ApiDtos.SearchResult(userService.search(trimmed, 12), posts, topicService.search(trimmed, 12));
    }
}
