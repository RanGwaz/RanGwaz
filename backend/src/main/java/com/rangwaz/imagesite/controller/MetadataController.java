package com.rangwaz.imagesite.controller;

import com.rangwaz.imagesite.common.api.ApiResponse;
import com.rangwaz.imagesite.dto.ApiDtos;
import com.rangwaz.imagesite.service.ImageMetadataService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

/**
 * Category and typed-tag metadata endpoints.
 */
@RestController
@RequestMapping("/metadata")
public class MetadataController {
    private final ImageMetadataService imageMetadataService;

    /**
     * Creates the metadata controller.
     *
     * @param imageMetadataService image metadata service
     */
    public MetadataController(ImageMetadataService imageMetadataService) {
        this.imageMetadataService = imageMetadataService;
    }

    /**
     * Lists the hierarchical image category tree.
     *
     * @return category tree
     */
    @GetMapping("/categories/tree")
    public ApiResponse<List<ApiDtos.CategoryView>> categoryTree() {
        return ApiResponse.ok(imageMetadataService.categoryTree());
    }

    /**
     * Lists typed tags.
     *
     * @param type optional tag type
     * @param limit maximum rows
     * @return tags
     */
    @GetMapping("/tags")
    public ApiResponse<List<ApiDtos.TagView>> tags(@RequestParam(required = false) String type,
                                                   @RequestParam(defaultValue = "100") int limit) {
        return ApiResponse.ok(imageMetadataService.tags(type, limit));
    }
}
