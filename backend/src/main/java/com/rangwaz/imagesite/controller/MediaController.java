package com.rangwaz.imagesite.controller;

import com.rangwaz.imagesite.common.api.ApiResponse;
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
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.multipart.MultipartFile;

import java.time.Duration;

/**
 * Media upload endpoints.
 */
@RestController
@RequestMapping("/api/media")
public class MediaController {
    private final MediaService mediaService;

    /**
     * Creates the media controller.
     *
     * @param mediaService media service
     */
    public MediaController(MediaService mediaService) {
        this.mediaService = mediaService;
    }

    /**
     * Uploads a local development image.
     *
     * @param file image file
     * @return upload response
     */
    @PostMapping("/upload")
    public ApiResponse<ApiDtos.UploadResponse> upload(@RequestParam("file") MultipartFile file) {
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
        String prefix = request.getContextPath() + "/api/media/object/";
        String objectKey = request.getRequestURI().substring(prefix.length());
        MediaObject media = mediaService.read(objectKey);
        return ResponseEntity.ok()
                .contentType(MediaType.parseMediaType(media.contentType()))
                .cacheControl(CacheControl.maxAge(Duration.ofDays(30)).cachePublic())
                .body(media.content());
    }
}
