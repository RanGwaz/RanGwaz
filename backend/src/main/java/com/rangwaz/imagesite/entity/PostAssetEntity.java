package com.rangwaz.imagesite.entity;

import lombok.Data;

import java.time.LocalDateTime;

/**
 * Database entity for a media asset attached to a post.
 */
@Data
public class PostAssetEntity {
    private Long id;
    private Long postId;
    private String objectKey;
    private String fileUrl;
    private String fileType;
    private String thumbUrl;
    private Integer width;
    private Integer height;
    private Integer sortOrder;
    private LocalDateTime createdAt;
}
