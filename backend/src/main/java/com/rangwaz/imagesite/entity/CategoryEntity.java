package com.rangwaz.imagesite.entity;

import lombok.Data;

import java.time.LocalDateTime;

/**
 * Hierarchical category for image navigation.
 */
@Data
public class CategoryEntity {
    private Long id;
    private String name;
    private Long parentId;
    private String slug;
    private Integer sortNo;
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;
}
