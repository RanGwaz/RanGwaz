package com.rangwaz.imagesite.controller;

import com.rangwaz.imagesite.common.api.ApiResponse;
import com.rangwaz.imagesite.dto.ApiDtos;
import com.rangwaz.imagesite.service.MediaService;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.multipart.MultipartFile;

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
}
