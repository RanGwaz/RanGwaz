package com.rangwaz.imagesite.entity;

import lombok.Data;

import java.math.BigDecimal;
import java.time.LocalDateTime;

/**
 * Tag assignment for an image with confidence and source.
 */
@Data
public class ImageTagEntity {
    private Long imageId;
    private Long tagId;
    private BigDecimal confidence;
    private String source;
    private LocalDateTime createdAt;
}
