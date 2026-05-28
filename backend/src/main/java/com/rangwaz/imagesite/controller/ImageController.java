package com.rangwaz.imagesite.controller;

import com.rangwaz.imagesite.common.api.ApiResponse;
import com.rangwaz.imagesite.common.auth.AuthContext;
import com.rangwaz.imagesite.dto.ApiDtos;
import com.rangwaz.imagesite.service.ImageService;
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
 * Image endpoints for publishing, detail reading, and analytics events.
 */
@RestController
@RequestMapping("/images")
public class ImageController {
    private final ImageService imageService;
    private final AuthContext authContext;

    /**
     * Creates the image controller.
     *
     * @param imageService image content service
     * @param authContext auth context
     */
    public ImageController(ImageService imageService, AuthContext authContext) {
        this.imageService = imageService;
        this.authContext = authContext;
    }

    /**
     * Creates a new image content row.
     *
     * @param authorization authorization header
     * @param request creation request
     * @return created image
     */
    @PostMapping
    public ApiResponse<ApiDtos.ImageView> create(@RequestHeader(value = "Authorization", required = false) String authorization,
                                                @Valid @RequestBody ApiDtos.CreateImageRequest request) {
        return ApiResponse.ok(imageService.create(authContext.requireUserId(authorization), request));
    }

    /**
     * Reads an image detail.
     *
     * @param authorization authorization header
     * @param imageId image id
     * @return image detail
     */
    @GetMapping("/{imageId}")
    public ApiResponse<ApiDtos.ImageView> detail(@RequestHeader(value = "Authorization", required = false) String authorization,
                                                @PathVariable Long imageId) {
        Long userId = authContext.currentUserId(authorization).orElse(null);
        return ApiResponse.ok(imageService.detail(imageId, userId));
    }

    /**
     * Tracks an image click.
     *
     * @param authorization authorization header
     * @param imageId image id
     * @param scene scene name
     * @param position feed position
     * @return empty response
     */
    @PostMapping("/{imageId}/click")
    public ApiResponse<Void> click(@RequestHeader(value = "Authorization", required = false) String authorization,
                                   @PathVariable Long imageId,
                                   @RequestParam(defaultValue = "feed") String scene,
                                   @RequestParam(required = false) Integer position) {
        Long userId = authContext.currentUserId(authorization).orElse(null);
        imageService.click(imageId, userId, scene, position);
        return ApiResponse.ok(null);
    }

    /**
     * Tracks an image share.
     *
     * @param imageId image id
     * @return empty response
     */
    @PostMapping("/{imageId}/share")
    public ApiResponse<Void> share(@PathVariable Long imageId) {
        imageService.share(imageId);
        return ApiResponse.ok(null);
    }
}
