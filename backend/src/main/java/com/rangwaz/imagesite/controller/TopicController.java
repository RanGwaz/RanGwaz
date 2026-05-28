package com.rangwaz.imagesite.controller;

import com.rangwaz.imagesite.common.api.ApiResponse;
import com.rangwaz.imagesite.dto.ApiDtos;
import com.rangwaz.imagesite.service.TopicService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

/**
 * Topic discovery endpoints.
 */
@RestController
@RequestMapping("/topics")
public class TopicController {
    private final TopicService topicService;

    /**
     * Creates the topic controller.
     *
     * @param topicService topic service
     */
    public TopicController(TopicService topicService) {
        this.topicService = topicService;
    }

    /**
     * Lists trending topics.
     *
     * @param limit maximum rows
     * @return topics
     */
    @GetMapping("/trending")
    public ApiResponse<List<ApiDtos.TopicView>> trending(@RequestParam(defaultValue = "20") int limit) {
        return ApiResponse.ok(topicService.trending(limit));
    }

    /**
     * Searches topics.
     *
     * @param keyword keyword
     * @param limit maximum rows
     * @return topics
     */
    @GetMapping("/search")
    public ApiResponse<List<ApiDtos.TopicView>> search(@RequestParam(defaultValue = "") String keyword,
                                                       @RequestParam(defaultValue = "20") int limit) {
        return ApiResponse.ok(topicService.search(keyword, limit));
    }
}
