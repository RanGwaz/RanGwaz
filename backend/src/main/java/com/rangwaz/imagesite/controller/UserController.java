package com.rangwaz.imagesite.controller;

import com.rangwaz.imagesite.common.api.ApiResponse;
import com.rangwaz.imagesite.common.auth.AuthContext;
import com.rangwaz.imagesite.dto.ApiDtos;
import com.rangwaz.imagesite.service.PostService;
import com.rangwaz.imagesite.service.UserService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

/**
 * User profile endpoints.
 */
@RestController
@RequestMapping("/api/users")
public class UserController {
    private final UserService userService;
    private final PostService postService;
    private final AuthContext authContext;

    /**
     * Creates the user controller.
     *
     * @param userService user service
     * @param postService post service
     * @param authContext auth context
     */
    public UserController(UserService userService, PostService postService, AuthContext authContext) {
        this.userService = userService;
        this.postService = postService;
        this.authContext = authContext;
    }

    /**
     * Reads a user profile.
     *
     * @param userId user id
     * @return user summary
     */
    @GetMapping("/{userId}")
    public ApiResponse<ApiDtos.UserSummary> profile(@PathVariable Long userId) {
        return ApiResponse.ok(userService.findSummary(userId));
    }

    /**
     * Reads user statistics.
     *
     * @param userId user id
     * @return user stats
     */
    @GetMapping("/{userId}/stats")
    public ApiResponse<ApiDtos.UserStats> stats(@PathVariable Long userId) {
        return ApiResponse.ok(userService.stats(userId));
    }

    /**
     * Lists a user's posts.
     *
     * @param userId user id
     * @param limit maximum rows
     * @return post list
     */
    @GetMapping("/{userId}/posts")
    public ApiResponse<List<ApiDtos.PostView>> posts(@PathVariable Long userId,
                                                     @RequestParam(defaultValue = "30") int limit) {
        return ApiResponse.ok(postService.byUser(userId, limit));
    }

    /**
     * Updates the current user's profile.
     *
     * @param authorization authorization header
     * @param request update request
     * @return updated summary
     */
    @PutMapping("/me")
    public ApiResponse<ApiDtos.UserSummary> updateMe(@RequestHeader(value = "Authorization", required = false) String authorization,
                                                     @RequestBody ApiDtos.UpdateProfileRequest request) {
        return ApiResponse.ok(userService.updateProfile(authContext.requireUserId(authorization), request));
    }
}
