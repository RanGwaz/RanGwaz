package com.rangwaz.imagesite.controller;

import com.rangwaz.imagesite.common.api.ApiResponse;
import com.rangwaz.imagesite.common.api.PageResponse;
import com.rangwaz.imagesite.common.auth.AuthContext;
import com.rangwaz.imagesite.dto.ApiDtos;
import com.rangwaz.imagesite.service.FeedService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

/**
 * Feed endpoints for home and detail recommendations.
 */
@RestController
@RequestMapping("/feed")
public class FeedController {
    private final FeedService feedService;
    private final AuthContext authContext;

    /**
     * Creates the feed controller.
     *
     * @param feedService feed service
     * @param authContext auth context
     */
    public FeedController(FeedService feedService, AuthContext authContext) {
        this.feedService = feedService;
        this.authContext = authContext;
    }

    /**
     * Loads the home feed.
     *
     * @param authorization authorization header
     * @param page page number
     * @param pageSize page size
     * @param visitorId stable anonymous visitor id
     * @param feedSessionId stable frontend feed session id
     * @param refreshSeed seed used to keep one refresh's pagination stable
     * @param excludeIds image ids recently shown on the frontend
     * @return feed page
     */
    @GetMapping
    public ApiResponse<PageResponse<ApiDtos.ImageView>> home(@RequestHeader(value = "Authorization", required = false) String authorization,
                                                            @RequestParam(defaultValue = "1") int page,
                                                            @RequestParam(defaultValue = "30") int pageSize,
                                                            @RequestParam(required = false) String visitorId,
                                                            @RequestParam(required = false) String feedSessionId,
                                                            @RequestParam(required = false) String refreshSeed,
                                                            @RequestParam(required = false) List<Long> excludeIds) {
        Long userId = authContext.currentUserId(authorization).orElse(null);
        return ApiResponse.ok(feedService.home(userId, page, pageSize, visitorId, feedSessionId, refreshSeed, excludeIds));
    }

    /**
     * Loads similar posts for a detail page.
     *
     * @param postId post id
     * @param page page number
     * @param size page size
     * @return similar posts page
     */
    @GetMapping("/images/{imageId}/similar")
    public ApiResponse<PageResponse<ApiDtos.ImageView>> similar(@PathVariable Long imageId,
                                                               @RequestParam(defaultValue = "1") int page,
                                                               @RequestParam(defaultValue = "24") int size) {
        return ApiResponse.ok(feedService.similar(imageId, page, size));
    }
}
