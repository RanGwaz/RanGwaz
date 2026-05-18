package com.rangwaz.imagesite.controller;

import com.rangwaz.imagesite.common.api.ApiResponse;
import com.rangwaz.imagesite.common.auth.AuthContext;
import com.rangwaz.imagesite.dto.ApiDtos;
import com.rangwaz.imagesite.service.PostService;
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
 * Post endpoints for publishing, detail reading, and analytics events.
 */
@RestController
@RequestMapping("/api/posts")
public class PostController {
    private final PostService postService;
    private final AuthContext authContext;

    /**
     * Creates the post controller.
     *
     * @param postService post service
     * @param authContext auth context
     */
    public PostController(PostService postService, AuthContext authContext) {
        this.postService = postService;
        this.authContext = authContext;
    }

    /**
     * Creates a new post.
     *
     * @param authorization authorization header
     * @param request creation request
     * @return created post
     */
    @PostMapping
    public ApiResponse<ApiDtos.PostView> create(@RequestHeader(value = "Authorization", required = false) String authorization,
                                                @Valid @RequestBody ApiDtos.CreatePostRequest request) {
        return ApiResponse.ok(postService.create(authContext.requireUserId(authorization), request));
    }

    /**
     * Reads a post detail.
     *
     * @param authorization authorization header
     * @param postId post id
     * @return post detail
     */
    @GetMapping("/{postId}")
    public ApiResponse<ApiDtos.PostView> detail(@RequestHeader(value = "Authorization", required = false) String authorization,
                                                @PathVariable Long postId) {
        Long userId = authContext.currentUserId(authorization).orElse(null);
        return ApiResponse.ok(postService.detail(postId, userId));
    }

    /**
     * Tracks a post click.
     *
     * @param authorization authorization header
     * @param postId post id
     * @param scene scene name
     * @param position feed position
     * @return empty response
     */
    @PostMapping("/{postId}/click")
    public ApiResponse<Void> click(@RequestHeader(value = "Authorization", required = false) String authorization,
                                   @PathVariable Long postId,
                                   @RequestParam(defaultValue = "feed") String scene,
                                   @RequestParam(required = false) Integer position) {
        Long userId = authContext.currentUserId(authorization).orElse(null);
        postService.click(postId, userId, scene, position);
        return ApiResponse.ok(null);
    }

    /**
     * Tracks a post share.
     *
     * @param postId post id
     * @return empty response
     */
    @PostMapping("/{postId}/share")
    public ApiResponse<Void> share(@PathVariable Long postId) {
        postService.share(postId);
        return ApiResponse.ok(null);
    }
}
