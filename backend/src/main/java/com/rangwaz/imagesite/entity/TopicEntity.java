package com.rangwaz.imagesite.entity;

import lombok.Data;

import java.math.BigDecimal;
import java.time.LocalDateTime;

/**
 * Database entity for searchable and recommendable topics.
 */
@Data
public class TopicEntity {
    private Long id;
    private String name;
    private String slug;
    private String description;
    private String coverUrl;
    private Integer postCount;
    private Integer followerCount;
    private BigDecimal hotScore;
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;
}
