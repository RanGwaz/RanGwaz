package com.rangwaz.imagesite.service;

import com.rangwaz.imagesite.dto.ApiDtos;
import org.springframework.web.multipart.MultipartFile;

/**
 * Service interface for local media uploads.
 */
public interface MediaService {
    /**
     * Stores an uploaded image locally.
     *
     * @param file upload file
     * @return upload response
     */
    ApiDtos.UploadResponse upload(MultipartFile file);
}
