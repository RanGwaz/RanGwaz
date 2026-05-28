package com.rangwaz.imagesite.entity;

import lombok.Data;

import java.time.LocalDateTime;

/**
 * Database entity for user likes and favorites.
 */
@Data
public class UserInteractionEntity {
    private Long id;
    private Long userId;
    private Long imageId;
    private String interactionType;
    private Boolean active;
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;
}
