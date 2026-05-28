package com.rangwaz.imagesite.entity;

import lombok.Data;

import java.math.BigDecimal;
import java.time.LocalDateTime;

/**
 * Canonical content row for one stored image.
 */
@Data
public class ImageEntity {
    private Long id;
    private Long authorId;
    private String title;
    private String content;
    private String postType;
    private String description;
    private String objectKey;
    private String fileUrl;
    private String fileType;
    private String thumbnailUrl;
    private Integer width;
    private Integer height;
    private String ratio;
    private Long fileSize;
    private String hash;
    private Long mainCategoryId;
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
