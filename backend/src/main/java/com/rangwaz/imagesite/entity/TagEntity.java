package com.rangwaz.imagesite.entity;

import lombok.Data;

import java.time.LocalDateTime;

/**
 * Typed tag produced by users, scripts, or external vision models.
 */
@Data
public class TagEntity {
    private Long id;
    private String name;
    private String type;
    private String slug;
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;
}
