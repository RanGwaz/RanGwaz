package com.rangwaz.imagesite.entity;

import lombok.Data;

import java.math.BigDecimal;
import java.time.LocalDateTime;

/**
 * Flat image document used to build the search index.
 */
@Data
public class ImageSearchDocumentEntity {
    private Long id;
    private Long authorId;
    private String title;
    private String content;
    private String description;
    private String status;
    private String fileUrl;
    private String thumbnailUrl;
    private Integer width;
    private Integer height;
    private String ratio;
    private String authorUsername;
    private String authorNickname;
    private String categoryName;
    private String tagsCsv;
    private String topicsCsv;
    private BigDecimal hotScore;
    private LocalDateTime publishedAt;
    private LocalDateTime createdAt;
}
