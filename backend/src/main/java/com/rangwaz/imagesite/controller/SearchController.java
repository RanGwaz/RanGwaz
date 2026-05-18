package com.rangwaz.imagesite.controller;

import com.rangwaz.imagesite.common.api.ApiResponse;
import com.rangwaz.imagesite.dto.ApiDtos;
import com.rangwaz.imagesite.service.SearchService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/**
 * Global search endpoint.
 */
@RestController
@RequestMapping("/api/search")
public class SearchController {
    private final SearchService searchService;

    /**
     * Creates the search controller.
     *
     * @param searchService search service
     */
    public SearchController(SearchService searchService) {
        this.searchService = searchService;
    }

    /**
     * Searches the image site.
     *
     * @param keyword keyword
     * @return search result
     */
    @GetMapping
    public ApiResponse<ApiDtos.SearchResult> search(@RequestParam(defaultValue = "") String keyword) {
        return ApiResponse.ok(searchService.search(keyword));
    }
}
