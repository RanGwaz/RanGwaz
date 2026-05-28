package com.rangwaz.imagesite.service;

import com.rangwaz.imagesite.dto.ApiDtos;
import java.util.List;

/**
 * Service for neutral image metadata and external annotations.
 */
public interface ImageMetadataService {
    /**
     * Reads image metadata by image id.
     *
     * @param imageId image id
     * @return image metadata view
     */
    ApiDtos.ImageMetadataView findByImageId(Long imageId);

    /**
     * Lists category tree.
     *
     * @return category tree
     */
    List<ApiDtos.CategoryView> categoryTree();

    /**
     * Lists tags by type.
     *
     * @param type optional tag type
     * @param limit maximum rows
     * @return tags
     */
    List<ApiDtos.TagView> tags(String type, int limit);
}
