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
@RequestMapping("/interactions")
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
    @PostMapping("/images/{imageId}/like/toggle")
    public ApiResponse<ApiDtos.ToggleResult> toggleLike(@RequestHeader(value = "Authorization", required = false) String authorization,
                                                        @PathVariable Long imageId) {
        return ApiResponse.ok(interactionService.toggleLike(authContext.requireUserId(authorization), imageId));
    }

    /**
     * Toggles a favorite.
     *
     * @param authorization authorization header
     * @param postId post id
     * @return toggle result
     */
    @PostMapping("/images/{imageId}/favorite/toggle")
    public ApiResponse<ApiDtos.ToggleResult> toggleFavorite(@RequestHeader(value = "Authorization", required = false) String authorization,
                                                            @PathVariable Long imageId) {
        return ApiResponse.ok(interactionService.toggleFavorite(authContext.requireUserId(authorization), imageId));
    }

    /**
     * Gets current user's post interaction status.
     *
     * @param authorization authorization header
     * @param postId post id
     * @return status response
     */
    @GetMapping("/images/{imageId}/status")
    public ApiResponse<ApiDtos.ImageInteractionStatus> status(@RequestHeader(value = "Authorization", required = false) String authorization,
                                                             @PathVariable Long imageId) {
        return ApiResponse.ok(interactionService.status(authContext.requireUserId(authorization), imageId));
    }

    /**
     * Pages comments.
     *
     * @param postId post id
     * @param page page number
     * @param size page size
     * @return comment page
     */
    @GetMapping("/images/{imageId}/comments/page")
    public ApiResponse<PageResponse<ApiDtos.CommentView>> comments(@PathVariable Long imageId,
                                                                   @RequestParam(defaultValue = "1") int page,
                                                                   @RequestParam(defaultValue = "20") int size) {
        return ApiResponse.ok(interactionService.comments(imageId, page, size));
    }

    /**
     * Creates a comment.
     *
     * @param authorization authorization header
     * @param postId post id
     * @param request creation request
     * @return created comment
     */
    @PostMapping("/images/{imageId}/comments")
    public ApiResponse<ApiDtos.CommentView> comment(@RequestHeader(value = "Authorization", required = false) String authorization,
                                                    @PathVariable Long imageId,
                                                    @Valid @RequestBody ApiDtos.CreateCommentRequest request) {
        return ApiResponse.ok(interactionService.comment(authContext.requireUserId(authorization), imageId, request));
    }
}
