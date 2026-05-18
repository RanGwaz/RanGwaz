package com.rangwaz.imagesite.controller;

import com.rangwaz.imagesite.common.api.ApiResponse;
import com.rangwaz.imagesite.common.api.PageResponse;
import com.rangwaz.imagesite.common.auth.AuthContext;
import com.rangwaz.imagesite.dto.ApiDtos;
import com.rangwaz.imagesite.service.InteractionService;
import jakarta.validation.Valid;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/**
 * Interaction endpoints for likes, favorites, comments, and behavior tracking.
 */
@RestController
@RequestMapping("/api/interactions")
public class InteractionController {
    private final InteractionService interactionService;
    private final AuthContext authContext;

    /**
     * Creates the interaction controller.
     *
     * @param interactionService interaction service
     * @param authContext auth context
     */
    public InteractionController(InteractionService interactionService, AuthContext authContext) {
        this.interactionService = interactionService;
        this.authContext = authContext;
    }

    /**
     * Toggles a like.
     *
     * @param authorization authorization header
     * @param postId post id
     * @return toggle result
     */
    @PostMapping("/posts/{postId}/like/toggle")
    public ApiResponse<ApiDtos.ToggleResult> toggleLike(@RequestHeader(value = "Authorization", required = false) String authorization,
                                                        @PathVariable Long postId) {
        return ApiResponse.ok(interactionService.toggleLike(authContext.requireUserId(authorization), postId));
    }

    /**
     * Toggles a favorite.
     *
     * @param authorization authorization header
     * @param postId post id
     * @return toggle result
     */
    @PostMapping("/posts/{postId}/favorite/toggle")
    public ApiResponse<ApiDtos.ToggleResult> toggleFavorite(@RequestHeader(value = "Authorization", required = false) String authorization,
                                                            @PathVariable Long postId) {
        return ApiResponse.ok(interactionService.toggleFavorite(authContext.requireUserId(authorization), postId));
    }

    /**
     * Gets current user's post interaction status.
     *
     * @param authorization authorization header
     * @param postId post id
     * @return status response
     */
    @GetMapping("/posts/{postId}/status")
    public ApiResponse<ApiDtos.PostInteractionStatus> status(@RequestHeader(value = "Authorization", required = false) String authorization,
                                                             @PathVariable Long postId) {
        return ApiResponse.ok(interactionService.status(authContext.requireUserId(authorization), postId));
    }

    /**
     * Pages comments.
     *
     * @param postId post id
     * @param page page number
     * @param size page size
     * @return comment page
     */
    @GetMapping("/posts/{postId}/comments/page")
    public ApiResponse<PageResponse<ApiDtos.CommentView>> comments(@PathVariable Long postId,
                                                                   @RequestParam(defaultValue = "1") int page,
                                                                   @RequestParam(defaultValue = "20") int size) {
        return ApiResponse.ok(interactionService.comments(postId, page, size));
    }

    /**
     * Creates a comment.
     *
     * @param authorization authorization header
     * @param postId post id
     * @param request creation request
     * @return created comment
     */
    @PostMapping("/posts/{postId}/comments")
    public ApiResponse<ApiDtos.CommentView> comment(@RequestHeader(value = "Authorization", required = false) String authorization,
                                                    @PathVariable Long postId,
                                                    @Valid @RequestBody ApiDtos.CreateCommentRequest request) {
        return ApiResponse.ok(interactionService.comment(authContext.requireUserId(authorization), postId, request));
    }
}
