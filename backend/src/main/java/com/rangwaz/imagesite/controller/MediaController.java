package com.rangwaz.imagesite.controller;

import com.rangwaz.imagesite.common.api.ApiResponse;
import com.rangwaz.imagesite.common.auth.AuthContext;
import com.rangwaz.imagesite.dto.ApiDtos;
import com.rangwaz.imagesite.service.MediaObject;
import com.rangwaz.imagesite.service.MediaService;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.http.CacheControl;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.multipart.MultipartFile;

import java.time.Duration;

/**
 * Media upload endpoints.
 */
@RestController
@RequestMapping("/media")
public class MediaController {
    private final MediaService mediaService;
    private final AuthContext authContext;

    /**
     * Creates the media controller.
     *
     * @param mediaService media service
     * @param authContext auth context
     */
    public MediaController(MediaService mediaService, AuthContext authContext) {
        this.mediaService = mediaService;
        this.authContext = authContext;
    }

    /**
     * Uploads a local development image.
     *
     * @param authorization authorization header
     * @param file image file
     * @return upload response
     */
    @PostMapping("/upload")
    public ApiResponse<ApiDtos.UploadResponse> upload(@RequestHeader(value = "Authorization", required = false) String authorization,
                                                      @RequestParam("file") MultipartFile file) {
        authContext.requireUserId(authorization);
        return ApiResponse.ok(mediaService.upload(file));
    }

    /**
     * Reads a media object through the backend.
     *
     * @param request HTTP request
     * @return media bytes
     */
    @GetMapping("/object/**")
    public ResponseEntity<byte[]> object(HttpServletRequest request) {
        String prefix = request.getContextPath() + "/media/object/";
        String objectKey = request.getRequestURI().substring(prefix.length());
        MediaObject media = mediaService.read(objectKey);
        return ResponseEntity.ok()
                .contentType(MediaType.parseMediaType(media.contentType()))
                .cacheControl(CacheControl.maxAge(Duration.ofDays(30)).cachePublic())
                .body(media.content());
    }
}
