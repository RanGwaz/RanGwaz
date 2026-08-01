package com.rangwaz.imagesite.controller;

import com.rangwaz.imagesite.common.api.ApiResponse;
import com.rangwaz.imagesite.common.auth.AuthContext;
import com.rangwaz.imagesite.dto.ApiDtos;
import com.rangwaz.imagesite.service.ImageService;
import com.rangwaz.imagesite.service.InteractionService;
import com.rangwaz.imagesite.service.UserService;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.beans.factory.annotation.Value;
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
@RequestMapping("/users")
public class UserController {
    private final UserService userService;
    private final ImageService imageService;
    private final InteractionService interactionService;
    private final AuthContext authContext;
    private final boolean mediaUploadEnabled;

    /**
     * Creates the user controller.
     *
     * @param userService user service
     * @param imageService post service
     * @param interactionService interaction service
     * @param authContext auth context
     * @param mediaUploadEnabled whether profile media changes are enabled
     */
    public UserController(UserService userService,
                          ImageService imageService,
                          InteractionService interactionService,
                          AuthContext authContext,
                          @Value("${app.features.media-upload-enabled:false}") boolean mediaUploadEnabled) {
        this.userService = userService;
        this.imageService = imageService;
        this.interactionService = interactionService;
        this.authContext = authContext;
        this.mediaUploadEnabled = mediaUploadEnabled;
    }

    /**
     * Reads the current request client IP.
     *
     * @param request servlet request
     * @return client ip
     */
    @GetMapping("/client-ip")
    public ApiResponse<ApiDtos.ClientIpResponse> clientIp(HttpServletRequest request) {
        return ApiResponse.ok(new ApiDtos.ClientIpResponse(resolveClientIp(request)));
    }

    private String resolveClientIp(HttpServletRequest request) {
        String forwardedFor = request.getHeader("X-Forwarded-For");
        if (forwardedFor != null && !forwardedFor.isBlank()) {
            return forwardedFor.split(",")[0].trim();
        }
        String realIp = request.getHeader("X-Real-IP");
        if (realIp != null && !realIp.isBlank()) return realIp.trim();
        return request.getRemoteAddr();
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
    @GetMapping("/{userId}/images")
    public ApiResponse<List<ApiDtos.ImageView>> posts(@RequestHeader(value = "Authorization", required = false) String authorization,
                                                     @PathVariable Long userId,
                                                     @RequestParam(defaultValue = "30") int limit) {
        boolean includeReviewRows = authContext.currentUserId(authorization)
                .map(currentUserId -> currentUserId.equals(userId))
                .orElse(false);
        return ApiResponse.ok(imageService.byUser(userId, limit, includeReviewRows));
    }

    /**
     * Lists images liked by a user.
     *
     * @param userId user id
     * @param limit maximum rows
     * @return liked image list
     */
    @GetMapping("/{userId}/liked-images")
    public ApiResponse<List<ApiDtos.ImageView>> likedImages(@PathVariable Long userId,
                                                            @RequestParam(defaultValue = "12") int limit) {
        return ApiResponse.ok(interactionService.likedImages(userId, limit));
    }

    /**
     * Lists images favorited by a user.
     *
     * @param userId user id
     * @param limit maximum rows
     * @return favorite image list
     */
    @GetMapping("/{userId}/favorite-images")
    public ApiResponse<List<ApiDtos.ImageView>> favoriteImages(@PathVariable Long userId,
                                                               @RequestParam(defaultValue = "30") int limit) {
        return ApiResponse.ok(interactionService.favoriteImages(userId, limit));
    }

    /**
     * Lists users followed by a user.
     *
     * @param userId user id
     * @param limit maximum rows
     * @return followed users
     */
    @GetMapping("/{userId}/following")
    public ApiResponse<List<ApiDtos.UserSummary>> following(@PathVariable Long userId,
                                                            @RequestParam(defaultValue = "50") int limit) {
        return ApiResponse.ok(interactionService.following(userId, limit));
    }

    /**
     * Lists users following a user.
     *
     * @param userId user id
     * @param limit maximum rows
     * @return follower users
     */
    @GetMapping("/{userId}/followers")
    public ApiResponse<List<ApiDtos.UserSummary>> followers(@PathVariable Long userId,
                                                            @RequestParam(defaultValue = "50") int limit) {
        return ApiResponse.ok(interactionService.followers(userId, limit));
    }

    /**
     * Updates the current user's profile.
     *
     * @param authorization authorization header
     * @param request update request
     * @return created review request
     */
    @PutMapping("/me")
    public ApiResponse<ApiDtos.ProfileReviewView> updateMe(@RequestHeader(value = "Authorization", required = false) String authorization,
                                                           @RequestBody ApiDtos.UpdateProfileRequest request) {
        ApiDtos.UpdateProfileRequest safeRequest = mediaUploadEnabled
                ? request
                : new ApiDtos.UpdateProfileRequest(request.nickname(), null, null, request.bio());
        return ApiResponse.ok(userService.updateProfile(authContext.requireUserId(authorization), safeRequest));
    }

    /**
     * Gets the current user's latest profile review request.
     *
     * @param authorization authorization header
     * @return latest review
     */
    @GetMapping("/me/profile-review")
    public ApiResponse<ApiDtos.ProfileReviewView> latestProfileReview(@RequestHeader(value = "Authorization", required = false) String authorization) {
        return ApiResponse.ok(userService.latestProfileReview(authContext.requireUserId(authorization)));
    }

    /**
     * Lists current user's notifications.
     *
     * @param authorization authorization header
     * @param limit maximum rows
     * @return notifications
     */
    @GetMapping("/me/notifications")
    public ApiResponse<List<ApiDtos.NotificationView>> notifications(@RequestHeader(value = "Authorization", required = false) String authorization,
                                                                     @RequestParam(defaultValue = "20") int limit) {
        return ApiResponse.ok(userService.notifications(authContext.requireUserId(authorization), limit));
    }
}
