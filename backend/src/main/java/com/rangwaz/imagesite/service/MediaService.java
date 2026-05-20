package com.rangwaz.imagesite.service;

import com.rangwaz.imagesite.dto.ApiDtos;
import org.springframework.web.multipart.MultipartFile;

/**
 * Service interface for object-storage-backed media assets.
 */
public interface MediaService {
    /**
     * Stores an uploaded image.
     *
     * @param file upload file
     * @return upload response
     */
    ApiDtos.UploadResponse upload(MultipartFile file);

    /**
     * Reads an object by its storage key.
     *
     * @param objectKey object key
     * @return media object
     */
    MediaObject read(String objectKey);
}
