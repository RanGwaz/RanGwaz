package com.rangwaz.imagesite.controller;

import com.rangwaz.imagesite.common.api.ApiResponse;
import com.rangwaz.imagesite.common.auth.AuthContext;
import com.rangwaz.imagesite.dto.ApiDtos;
import com.rangwaz.imagesite.service.InteractionService;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/**
 * Social relationship endpoints.
 */
@RestController
@RequestMapping("/api/social")
public class SocialController {
    private final InteractionService interactionService;
    private final AuthContext authContext;

    /**
     * Creates the social controller.
     *
     * @param interactionService interaction service
     * @param authContext auth context
     */
    public SocialController(InteractionService interactionService, AuthContext authContext) {
        this.interactionService = interactionService;
        this.authContext = authContext;
    }

    /**
     * Follows a user.
     *
     * @param authorization authorization header
     * @param userId target user id
     * @param scene scene name
     * @return empty response
     */
    @PostMapping("/follow/{userId}")
    public ApiResponse<Void> follow(@RequestHeader(value = "Authorization", required = false) String authorization,
                                    @PathVariable Long userId,
                                    @RequestParam(defaultValue = "unknown") String scene) {
        interactionService.follow(authContext.requireUserId(authorization), userId, scene);
        return ApiResponse.ok(null);
    }

    /**
     * Unfollows a user.
     *
     * @param authorization authorization header
     * @param userId target user id
     * @return empty response
     */
    @DeleteMapping("/follow/{userId}")
    public ApiResponse<Void> unfollow(@RequestHeader(value = "Authorization", required = false) String authorization,
                                      @PathVariable Long userId) {
        interactionService.unfollow(authContext.requireUserId(authorization), userId);
        return ApiResponse.ok(null);
    }

    /**
     * Gets follow status.
     *
     * @param authorization authorization header
     * @param userId target user id
     * @return status response
     */
    @GetMapping("/follow-status/{userId}")
    public ApiResponse<ApiDtos.FollowStatus> status(@RequestHeader(value = "Authorization", required = false) String authorization,
                                                    @PathVariable Long userId) {
        Long followerId = authContext.currentUserId(authorization).orElse(null);
        return ApiResponse.ok(interactionService.followStatus(followerId, userId));
    }
}
