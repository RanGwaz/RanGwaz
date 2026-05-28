package com.rangwaz.imagesite.entity;

import lombok.Data;

/**
 * Database entity for image behavior events.
 */
@Data
public class UserBehaviorEntity {
    private Long userId;
    private Long imageId;
    private String behaviorType;
    private String scene;
    private Integer positionNo;
    private Integer durationMs;
}
