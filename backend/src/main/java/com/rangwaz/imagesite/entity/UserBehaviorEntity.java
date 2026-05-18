package com.rangwaz.imagesite.entity;

import lombok.Data;

/**
 * Database entity for feed behavior events used by future recommendation jobs.
 */
@Data
public class UserBehaviorEntity {
    private Long userId;
    private Long postId;
    private String behaviorType;
    private String scene;
    private Integer positionNo;
    private Integer durationMs;
}
