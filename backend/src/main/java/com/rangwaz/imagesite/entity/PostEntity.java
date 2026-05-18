package com.rangwaz.imagesite.entity;

import lombok.Data;

import java.math.BigDecimal;
import java.time.LocalDateTime;

/**
 * Database entity for an image post.
 */
@Data
public class PostEntity {
    private Long id;
    private Long authorId;
    private String title;
    private String content;
    private String coverUrl;
    private String thumbUrl;
    private String postType;
    private String status;
    private Integer likeCount;
    private Integer favoriteCount;
    private Integer commentCount;
    private Integer shareCount;
    private Integer viewCount;
    private BigDecimal hotScore;
    private LocalDateTime publishedAt;
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;
}
